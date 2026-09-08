"""The screen-edge glow's window - fifth sibling of the overlay pattern.

Same child-process-and-command-queue shape as the blob, countdown, caption
and cursor windows; see `debug_window.py`, which established it, for why the
win32 message pump gets its own process.

What is specific here is the size and the lifetime. This one covers the
entire virtual desktop, and it is on exactly while Hey Peer is doing
something - it appears with the wake word and fades out when the exchange
ends, which is what makes it mean "the assistant is up" rather than
decorating the screen permanently.

## Why it does not simply appear and vanish

A border that blinks on at full strength is startling in peripheral vision,
which is the only place it is ever seen - nobody looks at the edge of their
screen. It fades in over a few frames and out again, so it registers as the
room changing rather than as something flashing at you.

## Cost

The full-screen bitmap is the expensive part of this pattern, so it is
redrawn at a deliberately low rate: the hue travels slowly by design (see
`screen_glow_render.HUE_SPEED`), and at that speed twelve frames a second
is indistinguishable from sixty while costing a fifth as much.
"""

import multiprocessing
import time

FRAME_SECONDS = 1 / 12

# How long the glow takes to reach full strength, and to leave. Long enough
# to read as a fade rather than a switch, short enough that the glow is
# established before Hey Peer has finished its first sentence.
# Matched to debug_window.SLIDE_SECONDS so the border and the blob land
# together. They are triggered on the same line, but the blob *slides* in
# over 0.28s while this was fading over 0.35s, so the glow was visibly the
# slower of the two - the user saw them arrive separately.
FADE_IN_SECONDS = 0.28
FADE_OUT_SECONDS = 0.5

# How often the idle process wakes to check for a "show". At 0.25s the
# border could start up to a quarter-second after the blob for no reason
# other than where in the cycle the message landed - which on a 0.28s fade
# is most of it. Cheap: an empty loop iteration on a sleeping process.
IDLE_POLL_SECONDS = 0.03


def _virtual_screen() -> "tuple[int, int, int, int]":
    """`(left, top, width, height)` of the whole virtual desktop - every
    monitor, not just the primary one, so the glow frames what the user is
    actually looking at on a multi-screen setup."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return (
            user32.GetSystemMetrics(76),   # SM_XVIRTUALSCREEN
            user32.GetSystemMetrics(77),   # SM_YVIRTUALSCREEN
            user32.GetSystemMetrics(78),   # SM_CXVIRTUALSCREEN
            user32.GetSystemMetrics(79),   # SM_CYVIRTUALSCREEN
        )
    except Exception:
        return (0, 0, 1920, 1080)


def _window_process(command_queue) -> None:
    from heypeer.tray.overlay import Overlay, is_supported
    from heypeer.tray.screen_glow_render import render

    def _drain_until_quit() -> None:
        while True:
            if command_queue.get()[0] == "quit":
                return

    if not is_supported():
        return _drain_until_quit()

    left, top, width, height = _virtual_screen()
    overlay = Overlay(width, height, title="Hey Peer Glow")
    if not overlay.create():
        return _drain_until_quit()

    phase = 0.0
    intensity = 0.0
    target = 0.0
    visible = False
    last = time.time()

    while True:
        overlay.pump_messages()
        try:
            kind, _payload = command_queue.get(
                timeout=FRAME_SECONDS if (visible or intensity > 0) else IDLE_POLL_SECONDS
            )
            if kind == "quit":
                overlay.destroy()
                return
            if kind == "show":
                target = 1.0
            elif kind == "hide":
                target = 0.0
        except Exception:
            pass

        now = time.time()
        dt = now - last
        last = now

        if intensity < target:
            intensity = min(target, intensity + dt / FADE_IN_SECONDS)
        elif intensity > target:
            intensity = max(target, intensity - dt / FADE_OUT_SECONDS)

        if intensity <= 0:
            if visible:
                overlay.set_visible(False)
                visible = False
            continue

        phase += dt
        overlay.update(render(width, height, phase=phase, intensity=intensity), left, top)
        if not visible:
            overlay.set_visible(True)
            visible = True


class ScreenGlowWindow:
    """Parent-side handle. Best-effort throughout - the glow says Hey Peer
    is active, and its failure must never affect whether it actually is."""

    def __init__(self) -> None:
        self._queue: multiprocessing.Queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_window_process, args=(self._queue,), daemon=True
        )
        self._process.start()
        self._shown = False

    def _send(self, kind: str) -> None:
        try:
            self._queue.put((kind, None))
        except Exception:
            pass

    def show(self) -> None:
        if self._shown:
            return  # already up; re-sending would restart nothing but cost a wake
        self._shown = True
        self._send("show")

    def hide(self) -> None:
        if not self._shown:
            return
        self._shown = False
        self._send("hide")

    def close(self) -> None:
        self._send("quit")
