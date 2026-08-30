"""Cross-platform active-window lookup (Windows/macOS/Linux via pywinctl).

`pywinctl` is imported inside `get_active_window` rather than at module
level on purpose: on Windows it pulls in pywin32 and comtypes, which is one
of the slowest imports in the whole app. Input capture — the only thing that
calls this — is off by default now, so paying that cost at startup for a
feature nobody enabled was pure waste.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveWindow:
    app_name: str
    title: str


def get_active_window() -> ActiveWindow | None:
    """Returns the currently focused app/window, or None if it can't be
    determined (e.g. no window manager, or between focus changes)."""
    import pywinctl

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
