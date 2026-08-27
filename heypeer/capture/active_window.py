"""Cross-platform active-window lookup (Windows/macOS/Linux via pywinctl)."""

from dataclasses import dataclass

import pywinctl


@dataclass(frozen=True)
class ActiveWindow:
    app_name: str
    title: str


def get_active_window() -> ActiveWindow | None:
    """Returns the currently focused app/window, or None if it can't be
    determined (e.g. no window manager, or between focus changes)."""
    window = pywinctl.getActiveWindow()
    if window is None:
        return None
    try:
        app_name = window.getAppName()
    except Exception:
        app_name = ""
    try:
        title = window.title
    except Exception:
        title = ""
    return ActiveWindow(app_name=app_name, title=title)
