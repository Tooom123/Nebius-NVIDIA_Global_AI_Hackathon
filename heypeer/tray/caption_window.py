"""The caption panel's window - the third of the overlay siblings, after
`debug_window.py` (the blob) and `countdown_window.py`.

Same child-process-plus-command-queue shape, for the same reasons; see
`debug_window.py`, which established it. What is specific here is the
lifetime: a caption is shown for a while and then goes away on its own,
where the blob follows the turn and the countdown follows the timers.

The dismissal delay scales with how much there is to read. A fixed timeout
either rushes a paragraph off the screen or leaves "c'est fait" sitting
there long after it stopped being relevant.
"""

import multiprocessing
import time

# Reading time, roughly. Deliberately generous: this is glanced at, often
# by someone in the middle of something else, and re-asking because the
# panel vanished is a much worse outcome than a panel that lingered.
SECONDS_PER_LINE = 2.6
MIN_SECONDS = 4.0
MAX_SECONDS = 25.0

POLL_SECONDS = 0.2


def dismiss_after(line_count: int) -> float:
    """How long a caption of `line_count` lines should stay up."""
    return max(MIN_SECONDS, min(MAX_SECONDS, line_count * SECONDS_PER_LINE))


def _screen_size() -> "tuple[int, int]":
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def _window_process(command_queue) -> None:
    from heypeer.tray.caption_render import position, render
    from heypeer.tray.overlay import Overlay, is_supported

    def _drain_until_quit() -> None:
        while True:
            if command_queue.get()[0] == "quit":
                return

    if not is_supported():
        return _drain_until_quit()

    screen_w, screen_h = _screen_size()
    # Sized to the tallest panel that can occur, then moved so its *visible*
    # content sits where it should: the window cannot be resized per caption
    # without recreating it, and recreating a layered window per answer
    # flickers.
    overlay = Overlay(_max_width(), _max_height(), title="Hey Peer Caption")
    if not overlay.create():
        return _drain_until_quit()

    visible = False
    hide_at = 0.0

    while True:
        overlay.pump_messages()
        try:
            kind, payload = command_queue.get(timeout=POLL_SECONDS)
            if kind == "quit":
                overlay.destroy()
                return
            if kind == "show":
                image = render(payload)
                if image is not None:
                    x, y = position(screen_w, screen_h, image.height)
                    padded = _pad_to_window(image, _max_width(), _max_height())
                    overlay.update(padded, x, y - (_max_height() - image.height))
                    overlay.set_visible(True)
                    visible = True
                    hide_at = time.time() + dismiss_after(_line_count(image.height))
            elif kind == "hide":
                overlay.set_visible(False)
                visible = False
        except Exception:
            pass

        if visible and time.time() >= hide_at:
            overlay.set_visible(False)
            visible = False


def _max_width() -> int:
    from heypeer.tray.caption_render import WIDTH

    return WIDTH


def _max_height() -> int:
    from heypeer.tray.caption_render import LINE_HEIGHT, MARGIN, MAX_LINES

    return 2 * MARGIN + LINE_HEIGHT * MAX_LINES


def _line_count(panel_height: int) -> int:
    from heypeer.tray.caption_render import LINE_HEIGHT, MARGIN

    return max(1, (panel_height - 2 * MARGIN) // LINE_HEIGHT)


def _pad_to_window(image, width: int, height: int):
    """Places a shorter panel at the bottom of a fixed-size transparent
    surface, so one window size serves every caption length."""
    from PIL import Image

    if image.height == height and image.width == width:
        return image
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(image, (0, height - image.height))
    return canvas


class CaptionWindow:
    """Parent-side handle. Best-effort throughout: a caption is a
    convenience, and its failure must never affect what was spoken."""

    def __init__(self) -> None:
        self._queue: multiprocessing.Queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_window_process, args=(self._queue,), daemon=True
        )
        self._process.start()

    def _send(self, kind: str, payload=None) -> None:
        try:
            self._queue.put((kind, payload))
        except Exception:
            pass

    def show(self, text: str) -> None:
        self._send("show", text)

    def hide(self) -> None:
        self._send("hide")

    def close(self) -> None:
        self._send("quit")
