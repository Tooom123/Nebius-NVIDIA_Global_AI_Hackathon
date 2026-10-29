"""The live transcript's window - sixth sibling of the overlay pattern.

Same child-process shape as the others (see `debug_window.py`). What is
specific here is that the child owns the typing: the parent hands over a
whole line and says who is speaking, and the child reveals it character by
character on its own clock.

That split matters. Sending a frame per character would make the typing
speed depend on queue latency and scheduler jitter, and the effect only
works if it is even. The parent knows *what* is being said; the child knows
when each frame is drawn, so it is the one that can pace it.

## Following the blob

The panel sits beside the blob, which follows the cursor, so its position
is re-read every frame rather than fixed at show time.
"""

import multiprocessing
import time

FRAME_SECONDS = 1 / 30

# Characters per second. The user's own words are revealed fast - they
# already know what they said, and slow dictation feels like lag. Hey Peer's
# are paced closer to speech, so the eye is not sentences ahead of the
# voice.
USER_CPS = 55.0
PEER_CPS = 26.0

# How long a finished line stays before fading, when nothing replaces it.
LINGER_SECONDS = 2.5


def _window_process(command_queue) -> None:
    from heypeer.tray import transcript_render as tr
    from heypeer.tray.overlay import Overlay, is_supported

    def _drain_until_quit() -> None:
        while True:
            if command_queue.get()[0] == "quit":
                return

    if not is_supported():
        return _drain_until_quit()

    height = 2 * tr.MARGIN + tr.LINE_HEIGHT * tr.MAX_LINES
    overlay = Overlay(tr.WIDTH, height, title="Hey Peer Transcript")
    if not overlay.create():
        return _drain_until_quit()

    from heypeer.tray.overlay import stage_rect

    stage_left, stage_top, screen_width, screen_height = stage_rect()
    text = ""
    cps = USER_CPS
    revealed = 0.0
    visible = False
    done_at = 0.0
    blob_box = (20, 20, 240)
    last = time.time()

    while True:
        overlay.pump_messages()
        try:
            kind, payload = command_queue.get(timeout=FRAME_SECONDS)
            if kind == "quit":
                overlay.destroy()
                return
            if kind == "say":
                # A new line replaces whatever was there: the panel holds
                # the present, never a log.
                text, who = payload
                cps = PEER_CPS if who == "peer" else USER_CPS
                revealed = 0.0
                done_at = 0.0
            elif kind == "blob":
                blob_box = payload
            elif kind == "clear":
                text = ""
        except Exception:
            pass

        now = time.time()
        dt = now - last
        last = now

        if not text:
            if visible:
                overlay.set_visible(False)
                visible = False
            continue

        revealed += cps * dt
        if revealed >= len(text):
            revealed = float(len(text))
            if done_at == 0.0:
                done_at = now
            elif now - done_at > LINGER_SECONDS:
                text = ""
                continue

        image = tr.render(text, int(revealed))
        if image is None:
            continue
        x, y = tr.position(screen_width, screen_height, image.height)
        x, y = x + stage_left, y + stage_top
        overlay.update(_pad(image, tr.WIDTH, height), x, y)
        if not visible:
            overlay.set_visible(True)
            visible = True


def _pad(image, width: int, height: int):
    """Centres a shorter panel in the fixed-size window, so one window size
    serves every line count without being recreated - recreating a layered
    window per line flickers."""
    from PIL import Image

    if image.size == (width, height):
        return image
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(image, (0, (height - image.height) // 2))
    return canvas


class TranscriptWindow:
    """Parent-side handle. Best-effort: the transcript is a convenience, and
    its failure must never affect what is heard."""

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

    def say(self, text: str, who: str = "peer") -> None:
        """Shows `text`, typed out. `who` is "user" or "peer" and only
        changes the speed."""
        self._send("say", (text, who))

    def follow_blob(self, x: int, y: int, size: int) -> None:
        self._send("blob", (x, y, size))

    def clear(self) -> None:
        self._send("clear")

    def close(self) -> None:
        self._send("quit")
