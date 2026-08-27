"""Minimal activity capture: abstracted input events + active app/window.

Records event types (click, key press, scroll, focus change), which app/window
was focused, and the minimal metadata needed to later replay the action
(coordinates, key name, scroll delta) — but never what a user typed into a
field, which is what "keystroke content" means here.
"""

from collections.abc import Callable

from heypeer.capture.active_window import ActiveWindow, get_active_window
from heypeer.capture.events import ActionEvent, ActionType

EventSink = Callable[[ActionEvent], None]


class ActivityWatcher:
    """Feeds abstracted ActionEvents to `on_event` as the user interacts with
    the machine. Scoped deliberately narrow: mouse clicks, key presses, scroll,
    and focus changes — enough to detect one demonstrable repeated pattern."""

    def __init__(self, on_event: EventSink) -> None:
        self._on_event = on_event
        self._current_window: ActiveWindow | None = None
        self._mouse_listener = None
        self._keyboard_listener = None

    def _emit(self, action_type: ActionType, **metadata: int | str | None) -> None:
        window = self._current_window or ActiveWindow(app_name="", title="")
        self._on_event(
            ActionEvent(
                type=action_type,
                app_name=window.app_name,
                window_title=window.title,
                **metadata,
            )
        )

    def _poll_active_window(self) -> None:
        window = get_active_window()
        if window is not None and window != self._current_window:
            self._current_window = window
            self._emit(ActionType.APP_FOCUS)

    def start(self) -> None:
        from pynput import keyboard, mouse

        self._poll_active_window()

        def on_click(x: int, y: int, button, pressed: bool) -> None:
            if pressed:
                self._poll_active_window()
                self._emit(ActionType.CLICK, x=int(x), y=int(y))

        def on_scroll(x: int, y: int, dx: int, dy: int) -> None:
            self._poll_active_window()
            self._emit(ActionType.SCROLL, scroll_dx=int(dx), scroll_dy=int(dy))

        def on_press(key) -> None:
            self._poll_active_window()
            # Special keys (Enter, Tab, arrows, ctrl/alt combos via their name)
            # are recorded by name since they're structural, not content. Plain
            # character keys are recorded as the generic "char" marker — never
            # the literal character — so typed text can never be reconstructed.
            key_name = getattr(key, "name", None) or "char"
            self._emit(ActionType.KEY_PRESS, key_name=key_name)

        self._mouse_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        self._keyboard_listener = keyboard.Listener(on_press=on_press)
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> None:
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
