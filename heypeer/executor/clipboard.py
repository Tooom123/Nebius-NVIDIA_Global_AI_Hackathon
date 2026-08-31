"""Reading and writing the clipboard, and copying whatever is currently
selected onto it.

There is no OS API to ask "what is the user's current text selection" for
an arbitrary, unknown application - only the application itself knows that.
The one thing every application already understands is Ctrl+C, so "copie
ça" is a simulated Ctrl+C keypress (the same `keybd_event` mechanism
`executor/system.py`'s volume keys and `executor/spotify.py`'s play/pause
key already use), not a read of some selection state this code cannot see.

Getting and setting the clipboard's own content uses `pyperclip` rather than
hand-rolled `ctypes` - unlike the window/volume control in `system.py`,
clipboard access genuinely needs format negotiation and `GlobalLock` retry
logic that is a known source of subtle bugs to get right by hand; `pyperclip`
is small, dependency-free, and already solves exactly this.
"""

import sys

_VK_CONTROL = 0x11
_VK_C = 0x43
_KEYEVENTF_KEYUP = 0x0002


def copy_selection() -> None:
    """Simulates Ctrl+C on whatever currently has keyboard focus. A no-op
    off Windows and if there is no selection to copy - both indistinguishable
    from here, and neither is an error."""
    if sys.platform != "win32":
        return
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(_VK_CONTROL, 0, 0, 0)
    user32.keybd_event(_VK_C, 0, 0, 0)
    user32.keybd_event(_VK_C, 0, _KEYEVENTF_KEYUP, 0)
    user32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)


def read() -> "str | None":
    """The clipboard's current text, or None if it is empty or not text (an
    image, a file list) - `pyperclip` raises for anything it cannot read as
    plain text, treated the same as "nothing there" rather than an error the
    caller has to handle separately."""
    import pyperclip

    try:
        text = pyperclip.paste()
    except Exception:
        return None
    return text or None


def write(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)
