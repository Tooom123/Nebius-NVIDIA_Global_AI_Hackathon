"""The countdown pill's window - a sibling of `debug_window.py`.

Same shape as the blob's window and for the same reasons: a child process
owning an `Overlay`, driven by a command queue, so a redraw loop can never
stall the turn handler and a UI failure can never take the app down with it
(see `debug_window.py`, which established this pattern).

The differences are what the countdown needs and the blob does not:

* It redraws on a timer of its own. The blob is driven by events - a state
  change, a microphone level - whereas a countdown changes because time
  passed and nothing happened. It ticks about twice a second, which is
  enough for a seconds display to never look stuck without spending frames
  on a pill that mostly shows the same digits.
* It shows whatever reminder is due soonest, and nothing when none is. The
  turn handler pushes the list; the child decides what that means visually.

`multiprocessing` rather than a thread, again matching the blob: the win32
message pump wants to own its thread, and keeping it out of the parent
means a wedged pump cannot wedge Hey Peer.
"""

import multiprocessing
import time

# How often the pill redraws while visible. Twice a second: a seconds
# counter that updates once a second visibly stutters when the tick and the
# second boundary drift apart, and going faster redraws identical digits.
TICK_SECONDS = 0.5

# Blocking wait while nothing is shown - the process should cost nothing
# when no timer is running, which is almost always.
IDLE_POLL_SECONDS = 0.25


def _screen_size() -> "tuple[int, int]":
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def _window_process(command_queue) -> None:
    """The child. Owns the overlay and the redraw loop."""
    from heypeer.tray.countdown_render import HEIGHT, WIDTH, position, render
    from heypeer.tray.overlay import Overlay, is_supported

    def _drain_until_quit() -> None:
        while True:
            if command_queue.get()[0] == "quit":
                return

    if not is_supported():
        return _drain_until_quit()

    overlay = Overlay(WIDTH, HEIGHT, title="Hey Peer Countdown")
    if not overlay.create():
        return _drain_until_quit()

    screen_w, screen_h = _screen_size()
    x, y = position(screen_w, screen_h)

    # (clock_text, label, fraction) or None for "nothing running".
    shown = None
    visible = False
    last_drawn = None

    while True:
        overlay.pump_messages()
        try:
            kind, payload = command_queue.get(
                timeout=IDLE_POLL_SECONDS if shown is None else TICK_SECONDS
            )
            if kind == "quit":
                overlay.destroy()
                return
            if kind == "show":
                shown = payload
            elif kind == "hide":
                shown = None
        except Exception:
            pass  # timed out: fall through and redraw the countdown

        if shown is None:
            if visible:
                overlay.set_visible(False)
                visible = False
                last_drawn = None
            continue

        clock_text, label, fraction = shown
        # Only push a bitmap when something actually changed - the pill is
        # mostly static between second boundaries, and UpdateLayeredWindow
        # is the expensive part of this loop.
        frame_key = (clock_text, label, round(fraction, 3))
        if frame_key != last_drawn:
            overlay.update(render(clock_text, label, fraction), x, y)
            last_drawn = frame_key
        if not visible:
            overlay.set_visible(True)
            visible = True


class CountdownWindow:
    """Parent-side handle. Every method is best-effort: the countdown is
    cosmetic, and a timer must still fire correctly if its display broke."""

    def __init__(self) -> None:
        self._queue: multiprocessing.Queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_window_process, args=(self._queue,), daemon=True
        )
        self._process.start()
        self._last_sent = None

    def _send(self, kind: str, payload=None) -> None:
        try:
            self._queue.put((kind, payload))
        except Exception:
            pass  # queue closed / process gone - never let the UI break a timer

    def show(self, clock_text: str, label: str, fraction_remaining: float) -> None:
        payload = (clock_text, label, float(fraction_remaining))
        if payload == self._last_sent:
            return  # nothing changed; don't wake the child to redraw the same frame
        self._last_sent = payload
        self._send("show", payload)

    def hide(self) -> None:
        if self._last_sent is None:
            return
        self._last_sent = None
        self._send("hide")

    def close(self) -> None:
        self._send("quit")


class CountdownDriver:
    """Keeps a `CountdownWindow` showing whatever reminder is due soonest.

    Split from the window so the "what should be on screen" decision is
    testable without a display: this class does the arithmetic, the window
    only draws what it is handed.
    """

    def __init__(self, store, window) -> None:
        self._store = store
        self._window = window

    def refresh(self) -> None:
        """Pushes the current state to the window. Called on a tick and
        whenever a reminder is created or cancelled."""
        from heypeer.executor.reminders import format_clock

        reminder = self._store.next_due()
        if reminder is None:
            self._window.hide()
            return
        remaining = reminder.remaining()
        # Guard the division: a zero-duration timer would otherwise be the
        # one input that crashes the display rather than showing 0:00.
        fraction = (
            remaining / reminder.duration_seconds if reminder.duration_seconds > 0 else 0.0
        )
        self._window.show(format_clock(remaining), reminder.label, fraction)

    def run_forever(self, stop_event) -> None:
        """Ticks until `stop_event` is set. Runs on its own daemon thread."""
        while not stop_event.wait(TICK_SECONDS):
            try:
                self.refresh()
            except Exception:
                pass  # a display failure must never stop the timers themselves
