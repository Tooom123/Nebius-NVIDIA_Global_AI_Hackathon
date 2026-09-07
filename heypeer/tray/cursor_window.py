"""The pointer's window - fourth sibling of the overlay pattern.

Same shape as `debug_window.py` (the blob), `countdown_window.py` and
`caption_window.py`: a child process owning an `Overlay`, driven by a
command queue. See the first of those for why - the win32 message pump
wants its own thread, and keeping it out of the parent means a wedged pump
cannot wedge Hey Peer.

What is specific here is that the animation is a *sequence with an end*,
not a state. The blob follows the turn, the countdown follows the timers,
the caption dismisses on a delay - this one plays a journey, presses, and
goes away. So the parent hands over a whole path in one message rather than
a position per frame: a queue round trip per frame would make the motion
depend on scheduler jitter, and the smoothness of the travel is the entire
point of drawing it.

## Why the click is timed by the child

The press happens at the end of the animation, and the two have to agree:
a click delivered before the pointer arrives looks like it pressed the
wrong place, and one delivered after the burst has faded looks like nothing
caused it. The child owns the frame clock, so it also signals the moment -
via an event the parent waits on, keeping `SendInput` in the parent where
the rest of the executor code lives.
"""

import multiprocessing
import time

# 60fps. The travel is short and the whole point is that it reads as
# movement rather than as a jump, which is where frame rate actually
# matters - unlike the countdown, redrawing twice a second.
FRAME_SECONDS = 1 / 60

# How long the journey takes, regardless of distance. Constant rather than
# speed-based so a cross-screen move and a short hop both feel deliberate;
# a constant *speed* makes long journeys tediously slow to watch.
TRAVEL_SECONDS = 0.55

# The press animation, after arrival.
PRESS_SECONDS = 0.22
# How long the pointer stays after the press before disappearing. Long
# enough to see what was clicked, short enough not to sit over the result.
LINGER_SECONDS = 0.45


def _screen_size() -> "tuple[int, int]":
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def _window_process(command_queue, click_event) -> None:
    """The child: owns the overlay and the frame clock."""
    from heypeer.tray import cursor_render
    from heypeer.tray.overlay import Overlay, is_supported

    def _drain_until_quit() -> None:
        while True:
            if command_queue.get()[0] == "quit":
                return

    if not is_supported():
        # Still signal the click, so a machine that cannot draw the pointer
        # can still press the button. The animation is the cosmetic half.
        while True:
            kind, _payload = command_queue.get()
            if kind == "quit":
                return
            if kind == "play":
                click_event.set()

    size = cursor_render.SURFACE * cursor_render.PIXEL_SCALE
    overlay = Overlay(size, size, title="Hey Peer Cursor")
    if not overlay.create():
        return _drain_until_quit()

    half = size // 2

    while True:
        overlay.pump_messages()
        try:
            kind, payload = command_queue.get(timeout=0.2)
        except Exception:
            continue

        if kind == "quit":
            overlay.destroy()
            return
        if kind == "color":
            cursor_render.set_color(payload)
            continue
        if kind != "play":
            continue

        start, end = payload
        steps = max(2, int(TRAVEL_SECONDS / FRAME_SECONDS))
        path = cursor_render.travel_path(start, end, steps)

        overlay.set_visible(True)
        for i, (x, y) in enumerate(path):
            frame_started = time.time()
            overlay.pump_messages()
            overlay.update(
                cursor_render.render(0.0, cursor_render.trail_offsets(path, i)),
                x - half,
                y - half,
            )
            _sleep_until(frame_started + FRAME_SECONDS)

        # Arrived. Tell the parent to press, then animate the press over
        # the same instant so the two are seen as one event.
        click_event.set()
        press_frames = max(1, int(PRESS_SECONDS / FRAME_SECONDS))
        for i in range(press_frames):
            frame_started = time.time()
            overlay.pump_messages()
            overlay.update(
                cursor_render.render((i + 1) / press_frames),
                end[0] - half,
                end[1] - half,
            )
            _sleep_until(frame_started + FRAME_SECONDS)

        overlay.update(cursor_render.render(0.0), end[0] - half, end[1] - half)
        _sleep_until(time.time() + LINGER_SECONDS)
        overlay.set_visible(False)


def _sleep_until(deadline: float) -> None:
    """Sleeps to `deadline`, or returns immediately if it has passed - so a
    slow frame shortens the next wait instead of accumulating drift."""
    remaining = deadline - time.time()
    if remaining > 0:
        time.sleep(remaining)


class CursorWindow:
    """Parent-side handle. Best-effort throughout: the pointer is the
    visible half of a click, and its failure must never stop the click."""

    def __init__(self) -> None:
        self._queue: multiprocessing.Queue = multiprocessing.Queue()
        self._click_event = multiprocessing.Event()
        self._process = multiprocessing.Process(
            target=_window_process, args=(self._queue, self._click_event), daemon=True
        )
        self._process.start()

    def _send(self, kind: str, payload=None) -> None:
        try:
            self._queue.put((kind, payload))
        except Exception:
            pass

    def set_color(self, rgb: "tuple[int, int, int]") -> None:
        """Applies the user's chosen pointer colour. Sent to the child
        because that is where rendering happens - the parent's own module
        state would have no effect on the drawn frames."""
        self._send("color", tuple(rgb))

    def play(self, start: "tuple[int, int]", end: "tuple[int, int]", timeout: float = 5.0) -> bool:
        """Animates a journey from `start` to `end` and blocks until the
        pointer has arrived, returning whether it did.

        Returning at *arrival* rather than at the end of the whole animation
        is what lets the caller click at the right moment: the press
        animation plays over the click rather than after it.

        A timeout means the child is wedged or gone. The caller clicks
        anyway - a button that gets pressed without the animation is a
        worse demo and a working feature; the reverse is neither.
        """
        self._click_event.clear()
        self._send("play", (tuple(start), tuple(end)))
        return self._click_event.wait(timeout)

    def close(self) -> None:
        self._send("quit")
