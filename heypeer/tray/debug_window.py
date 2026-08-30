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

## Cost

`render_alpha` is the expensive half (~18ms: polygon fill, blur,
supersampled downscale) but depends only on time and level, never on color.
So a loop of alpha frames is rendered **once** up front (~0.2s) and reused;
per frame only the cheap `compose` runs (~1.2ms, measured) — about 3.6% of
one core at 30fps, and only while the indicator is actually on screen.

Runs in its own process: a thread-based version once hung the entire
interpreter in this project's Linux sandbox, and `Process.start()` returns
immediately whatever the child does.

Windows-only, like `cursor.py`. Elsewhere it degrades to a no-op rather than
pretending to work.
"""

import multiprocessing
import time

# Palette per state: blue -> violet -> magenta, shifted per state. The shape
# language is identical across states, so a transition reads as one object
# reacting rather than a different indicator appearing.
STATE_PALETTES = {
    "idle": ((58, 74, 96), (74, 74, 106), (106, 74, 122)),
    "listening": ((79, 140, 255), (123, 77, 255), (224, 64, 251)),
    "recording": ((79, 140, 255), (139, 92, 255), (255, 79, 216)),
    "thinking": ((91, 109, 255), (155, 77, 255), (208, 64, 251)),
    "speaking": ((95, 168, 255), (160, 92, 255), (255, 106, 224)),
}

# Only shown while a turn is actually happening — the indicator should appear
# when Hey Peer has heard something, not sit on screen permanently.
_VISIBLE_STATES = {"recording", "thinking", "speaking"}

SIZE = 240
TOP_MARGIN = 12  # resting distance from the top edge of the screen

# Pre-rendered morph loop, per level bucket. The mic level changes the
# outline itself now (it deepens and speeds up the wobble, not just the
# size — see blob_shape), so a single loop can't be scaled to fake it; each
# bucket gets its own. 40 frames x 5 buckets ~= 1s of one-off work in the
# background process, and ~11 MB of masks.
LOOP_FRAMES = 40
LOOP_STEP_SECONDS = 0.28
LEVEL_BUCKETS = 5

# The raw mic level is jumpy; smoothing it keeps the blob from snapping
# between buckets on every syllable.
LEVEL_SMOOTHING = 0.25

FRAME_INTERVAL = 1 / 30
# While nothing is on screen — the overwhelmingly common case — idle cheaply
# instead of running the frame loop for nothing.
IDLE_POLL_INTERVAL = 0.1

# Exponential easing per frame for the slide, rather than a fixed duration,
# so a state change mid-slide retargets smoothly instead of jumping.
SLIDE_EASING = 0.24
SLIDE_SETTLED_PX = 2


def _screen_width(default: int = 1920) -> int:
    try:
        import ctypes

        return int(ctypes.windll.user32.GetSystemMetrics(0)) or default
    except Exception:
        return default


def _window_process(command_queue: "multiprocessing.Queue") -> None:
    """Owns the overlay window, the pre-rendered frames, and the animation."""
    from heypeer.tray.blob_render import compose, render_alpha
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

    # [bucket][frame] — indexed by smoothed level and animation time.
    frames = [
        [
            render_alpha(SIZE, t=i * LOOP_STEP_SECONDS, level=bucket / (LEVEL_BUCKETS - 1))
            for i in range(LOOP_FRAMES)
        ]
        for bucket in range(LEVEL_BUCKETS)
    ]

    x = max(0, (_screen_width() - SIZE) // 2)
    offscreen_y = -SIZE - 20

    state = "idle"
    visible = False
    level = 0.0
    smoothed_level = 0.0
    y = float(offscreen_y)
    on_screen = False
    started_at = time.time()

    while True:
        overlay.pump_messages()

        while not command_queue.empty():
            try:
                kind, payload = command_queue.get_nowait()
            except Exception:
                break
            if kind == "quit":
                overlay.destroy()
                return
            if kind == "level":
                level = payload
            elif kind == "state":
                state = payload
                visible = payload in _VISIBLE_STATES

        if not on_screen and not visible:
            time.sleep(IDLE_POLL_INTERVAL)
            continue

        if visible and not on_screen:
            y = float(offscreen_y)
            on_screen = True
            overlay.set_visible(True)

        target_y = float(TOP_MARGIN if visible else offscreen_y)
        y += (target_y - y) * SLIDE_EASING
        if abs(target_y - y) < SLIDE_SETTLED_PX:
            y = target_y

        smoothed_level += (level - smoothed_level) * LEVEL_SMOOTHING
        bucket = min(LEVEL_BUCKETS - 1, int(round(smoothed_level * (LEVEL_BUCKETS - 1))))
        frame = int((time.time() - started_at) / LOOP_STEP_SECONDS) % LOOP_FRAMES

        overlay.update(
            compose(frames[bucket][frame], STATE_PALETTES.get(state, STATE_PALETTES["idle"])),
            x,
            int(y),
        )

        if not visible and y == target_y:
            overlay.set_visible(False)
            on_screen = False

        time.sleep(FRAME_INTERVAL)


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
