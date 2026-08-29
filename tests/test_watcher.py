from unittest.mock import patch

from heypeer.capture.active_window import ActiveWindow
from heypeer.capture.events import ActionType
from heypeer.capture.watcher import ActivityWatcher


def test_poll_active_window_emits_focus_event_on_change() -> None:
    events = []
    watcher = ActivityWatcher(on_event=events.append)

    with patch(
        "heypeer.capture.watcher.get_active_window",
        return_value=ActiveWindow(app_name="Files", title="Downloads"),
    ):
        watcher._poll_active_window()
        watcher._last_window_poll -= 10  # bypass the throttle
        watcher._poll_active_window()  # same window again, no duplicate event

    assert len(events) == 1
    assert events[0].type == ActionType.APP_FOCUS
    assert events[0].app_name == "Files"


def test_poll_active_window_emits_again_on_window_change() -> None:
    events = []
    watcher = ActivityWatcher(on_event=events.append)

    with patch(
        "heypeer.capture.watcher.get_active_window",
        side_effect=[
            ActiveWindow(app_name="Files", title="Downloads"),
            ActiveWindow(app_name="Editor", title="notes.txt"),
        ],
    ):
        watcher._poll_active_window()
        # Polling is throttled (see ACTIVE_WINDOW_POLL_INTERVAL); pretend
        # enough time passed rather than sleeping through it.
        watcher._last_window_poll -= 10
        watcher._poll_active_window()

    assert [e.app_name for e in events] == ["Files", "Editor"]


def test_poll_active_window_is_throttled() -> None:
    """Regression test: this ran on every keypress/click/scroll, and
    `get_active_window()` is a Win32 + process lookup — one per typed
    character was making the user's machine noticeably slow."""
    events = []
    watcher = ActivityWatcher(on_event=events.append)

    with patch(
        "heypeer.capture.watcher.get_active_window",
        return_value=ActiveWindow(app_name="Files", title="Downloads"),
    ) as get_window:
        for _ in range(50):  # a burst of typing
            watcher._poll_active_window()

    assert get_window.call_count == 1
