"""The on-screen indicator: a soft, luminous blob that drops in from the top
of the screen when Hey Peer is activated, morphs organically, swells with the
user's voice, and slides back up when the turn is over.

## Why this no longer uses a web view

Five rounds tried to get a borderless, good-looking indicator out of
`pywebview`/WebView2, each failing on a different wrong assumption:

1. `shadow=False` + forcing the Chromium backend — real issues, rectangle
   remained.
2. A Win32 layered-window **color key** — cannot work: WebView2 renders
   through DirectComposition into its own child surface, which the parent's
   color-keying never sees.
3. pywebview's `transparent=True` — did make WebView2 transparent, revealing
   that its Windows backend never makes the WinForms *form* behind it
   transparent, so a grey rectangle stayed.
4. `SetWindowRgn` with a fixed ellipse — finally rectangle-free, but a static
   circle clipping an animated blob looked truncated.
5. `SetWindowRgn` with a per-frame polygon — correct shape, but a window
   region is a **1-bit mask**: hard, aliased edges, and a glow is impossible
   by construction.

Every one of those was an attempt to talk a browser engine into something
Win32 exposes directly. `UpdateLayeredWindow` composites a 32-bit BGRA
bitmap into the desktop with genuine per-pixel alpha — antialiased edges, a
real glow, no background at all. So the frame is rendered here with PIL
(`blob_render.py`) and pushed through `overlay.py`, and the browser engine
is gone along with its whole class of failure modes.

A useful side effect: the look is now *testable*. Alpha at the corners, edge
softness, the glow reaching past the silhouette, growth with mic level — all
assertable headlessly, none of which was checkable while the design lived in
CSS behind a web view.

## Smoothness

An earlier version pre-rendered a short loop of frames and cycled them,
because rendering cost ~18ms. The shape therefore advanced only a few times
a second and the motion looked stepped. `blob_render` now draws an analytic
radial field instead of rasterising a polygon and blurring it (~1.4ms,
measured), so every frame is rendered live at 30fps from continuously
varying parameters.

Nothing is set directly: amplitude, speed, glow and radius are all eased
toward their targets, which both gives the design's 400-700ms return to a
near-sphere and makes a visible jump impossible whatever changes. The noise
phase is *accumulated* rather than derived from wall-clock time, so a change
of speed bends the motion instead of teleporting it.

Runs in its own process: a thread-based version once hung the entire
interpreter in this project's Linux sandbox, and `Process.start()` returns
immediately whatever the child does.

Windows-only, like `cursor.py`. Elsewhere it degrades to a no-op rather than
pretending to work.
"""

import multiprocessing
import time

# Per state: how far the outline strays from a circle, how fast it churns,
# how strong the halo is, and how much the mic level adds to each. The
# palette is deliberately the same throughout - it is one object reacting,
# not a set of different indicators.
#
#   idle       barely breathing, a near-sphere
#   listening  mic open: a little more irregular, halo lifted
#   recording  driven by the voice - the level terms do the work
#   thinking   busy but not voice-driven
#   speaking   the most alive: broad lobes forming and dissolving
#   awaiting   a question was asked and the answer needs no wake word, so the
#              blob stays on screen: the exchange is still open
STATE_ENERGY = {
    "idle":      {"amplitude": 0.030, "speed": 0.35, "glow": 0.35, "level_gain": 0.0},
    "listening": {"amplitude": 0.070, "speed": 0.60, "glow": 0.50, "level_gain": 0.0},
    "awaiting":  {"amplitude": 0.075, "speed": 0.70, "glow": 0.55, "level_gain": 1.0},
    "recording": {"amplitude": 0.080, "speed": 0.80, "glow": 0.55, "level_gain": 1.0},
    "thinking":  {"amplitude": 0.120, "speed": 1.60, "glow": 0.60, "level_gain": 0.0},
    "speaking":  {"amplitude": 0.150, "speed": 1.10, "glow": 0.70, "level_gain": 0.6},
}

# What a full-scale mic level adds on top of the state's own values. These
# were far too timid: the radius term moved the shape by 1.5% at speaking
# volume, which is simply not visible. The voice still drives energy more
# than size, per the design, but all of it now by an amount the eye can see.
LEVEL_AMPLITUDE_GAIN = 0.15
LEVEL_SPEED_GAIN = 2.5
LEVEL_GLOW_GAIN = 0.40
LEVEL_RADIUS_GAIN = 0.14

# Only shown while a turn is actually happening - the indicator should appear
# when Hey Peer has heard something, not sit on screen permanently.
_VISIBLE_STATES = {"recording", "thinking", "speaking", "awaiting"}

SIZE = 240
TOP_MARGIN = 12  # resting distance from the top edge of the screen
# Leaves room for the glow, and for the outline at its most deformed.
BASE_RADIUS = SIZE * 0.26

FRAME_INTERVAL = 1 / 30
# While nothing is on screen - the overwhelmingly common case - idle cheaply
# instead of running the frame loop for nothing.
IDLE_POLL_INTERVAL = 0.1

# The slide runs on elapsed time, not on a per-frame easing factor. Easing
# per frame made its duration hostage to the frame rate: 18 frames is 0.6s at
# 30fps but 2.2s if anything slows the loop down, and the user saw the blob
# arrive well after they had started speaking. A duration is a duration.
SLIDE_SECONDS = 0.28

# State parameters are eased toward their target rather than set. At 30fps
# this settles in roughly half a second - the design's 400-700ms transition -
# and it makes a visible jump impossible whichever quantity moves.
ENERGY_EASING = 0.14
# The mic level is smoothed separately and much faster. Speech dynamics are
# quick, and running the level through the slow state easing as well damped
# the voice response into near-invisibility - the level was arriving, it just
# never reached the shape in time to show.
LEVEL_EASING = 0.45


def slide_position(from_y: float, to_y: float, elapsed: float) -> float:
    """Where the indicator sits `elapsed` seconds into a slide.

    Time-based, not a per-frame easing factor: easing per frame made the
    duration hostage to the frame rate, so any slowdown stretched the slide
    and the blob landed well after the user had started speaking.
    """
    progress = min(1.0, max(0.0, elapsed / SLIDE_SECONDS))
    eased = 1 - (1 - progress) ** 3  # quick to start, gentle to land
    return from_y + (to_y - from_y) * eased


def _screen_width(default: int = 1920) -> int:
    try:
        import ctypes

        return int(ctypes.windll.user32.GetSystemMetrics(0)) or default
    except Exception:
        return default


def _window_process(command_queue: "multiprocessing.Queue") -> None:
    """Owns the overlay window and the animation loop."""
    from heypeer.tray.blob_render import OUTLINE_ANGLES, render
    from heypeer.tray.blob_shape import radius_profile
    from heypeer.tray.overlay import Overlay, is_supported


    if not is_supported():
        # Drain commands so the parent never blocks on a full queue.
        while True:
            if command_queue.get()[0] == "quit":
                return

    overlay = Overlay(SIZE, SIZE)
    if not overlay.create():
        while True:
            if command_queue.get()[0] == "quit":
                return

    x = max(0, (_screen_width() - SIZE) // 2)
    offscreen_y = -SIZE - 20

    # Built once here rather than on the first visible frame, so the cue
    # doesn't pay for cache misses and GDI setup at the exact moment it is
    # meant to feel instant.
    render(SIZE, radius_profile(OUTLINE_ANGLES, 0.0, 0.03), BASE_RADIUS)
    overlay.update(render(SIZE, radius_profile(OUTLINE_ANGLES, 0.0, 0.03), BASE_RADIUS),
                   x, offscreen_y)

    state = "idle"
    visible = False
    level = 0.0
    smooth_level = 0.0
    slide_from = float(offscreen_y)
    slide_started_at = 0.0
    # Current (eased) animation parameters, started at the idle target so the
    # first frame isn't a jump from nothing.
    current = dict(STATE_ENERGY["idle"])
    current["radius"] = BASE_RADIUS
    phase = 0.0
    y = float(offscreen_y)
    on_screen = False
    last_frame_at = time.time()

    while True:
        overlay.pump_messages()

        # Blocking with a timeout while nothing is on screen, rather than
        # polling: a "show" used to wait out up to a full poll interval
        # before anything happened, which is dead time added to a cue that
        # has to feel immediate.
        idle = not on_screen and not visible
        try:
            kind, payload = command_queue.get(timeout=IDLE_POLL_INTERVAL if idle else 0)
            pending = [(kind, payload)]
        except Exception:
            pending = []
        while not command_queue.empty():
            try:
                pending.append(command_queue.get_nowait())
            except Exception:
                break

        for kind, payload in pending:
            if kind == "quit":
                overlay.destroy()
                return
            if kind == "level":
                level = payload
            elif kind == "state":
                was_visible = visible
                state = payload
                visible = payload in _VISIBLE_STATES
                if visible != was_visible:
                    slide_from = y
                    slide_started_at = time.time()

        if not on_screen and not visible:
            last_frame_at = time.time()
            continue

        if visible and not on_screen:
            y = float(offscreen_y)
            slide_from = y
            slide_started_at = time.time()
            on_screen = True
            overlay.set_visible(True)

        now = time.time()
        dt = min(now - last_frame_at, 0.1)  # a stall must not lurch the phase
        last_frame_at = now

        smooth_level += (level - smooth_level) * LEVEL_EASING
        target = STATE_ENERGY.get(state, STATE_ENERGY["idle"])

        # State parameters ease slowly (that is the transition); the voice
        # contribution is added on top *without* a second round of easing,
        # so speech shows immediately instead of being smoothed twice.
        for key in ("amplitude", "speed", "glow"):
            current[key] += (target[key] - current[key]) * ENERGY_EASING
        current["radius"] += (BASE_RADIUS - current["radius"]) * ENERGY_EASING

        gain = target["level_gain"] * smooth_level
        amplitude = current["amplitude"] + LEVEL_AMPLITUDE_GAIN * gain
        speed = current["speed"] + LEVEL_SPEED_GAIN * gain
        glow = current["glow"] + LEVEL_GLOW_GAIN * gain
        radius = current["radius"] * (1 + LEVEL_RADIUS_GAIN * gain)

        # Accumulated, not derived from wall-clock time: a change of speed
        # must bend the motion, never teleport the phase.
        phase += speed * dt

        target_y = float(TOP_MARGIN if visible else offscreen_y)
        elapsed = now - slide_started_at
        progress = min(1.0, elapsed / SLIDE_SECONDS)
        y = slide_position(slide_from, target_y, elapsed)

        radii = radius_profile(OUTLINE_ANGLES, phase, amplitude)
        overlay.update(render(SIZE, radii, radius, glow=glow), x, int(y))

        if not visible and progress >= 1.0:
            overlay.set_visible(False)
            on_screen = False

        # Sleep the remainder of the frame, not a whole interval on top of
        # the work already done - otherwise the real frame rate is always
        # below the nominal one.
        time.sleep(max(0.0, FRAME_INTERVAL - (time.time() - now)))


class DebugWindow:
    def __init__(self) -> None:
        self._queue: multiprocessing.Queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_window_process, args=(self._queue,), daemon=True
        )
        self._process.start()
        self._last_state: str | None = None

    def _send(self, kind: str, payload=None) -> None:
        try:
            self._queue.put((kind, payload))
        except Exception:
            pass  # queue closed / process gone — never let a UI hiccup break the app

    def set_level(self, level: float) -> None:
        self._send("level", float(max(0.0, min(1.0, level))))

    def set_state(self, state: str) -> None:
        """No-ops when the state hasn't changed. Called from the audio
        callback on every chunk (~12x/second), and each change drives a
        window transition."""
        if state == self._last_state:
            return
        self._last_state = state
        self._send("state", state)

    def close(self) -> None:
        self._send("quit")
