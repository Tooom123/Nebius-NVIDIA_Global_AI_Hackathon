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
        watcher._poll_active_window()

    assert [e.app_name for e in events] == ["Files", "Editor"]
