"""Bringing a window to the front, reliably, on Windows.

Three ways it went wrong on the demo machine, each looking like nothing
happened: SetForegroundWindow refused by Windows - it gives the foreground
only to a process that has had input recently, and says it succeeded
anyway; a minimised window activated without being restored, so it stayed
in the taskbar; and a window raised on whichever screen it last sat on.
One function, so every app the demo drives is raised the same way.
"""

import ctypes
import time

VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
SW_MAXIMIZE = 3
SWP_SHOWWINDOW = 0x0040
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2


def raise_window(handle: int, stage: "tuple[int, int, int, int] | None" = None,
                 maximize: bool = True) -> None:
    """Restores, optionally moves onto `stage` (left, top, width, height),
    maximises and brings `handle` to the front."""
    user32 = ctypes.windll.user32
    user32.ShowWindow(handle, SW_RESTORE)
    if stage is not None:
        left, top, width, height = stage
        user32.SetWindowPos(handle, 0, left, top, width, height, SWP_SHOWWINDOW)
    if maximize:
        user32.ShowWindow(handle, SW_MAXIMIZE)
    # Topmost and straight back: puts it above every other window whether
    # or not Windows grants the foreground - which it refuses while the
    # user is typing in another window, Alt tap or not. Measured: an IDE
    # in use stayed over FL Studio through every other step here.
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
    user32.SetWindowPos(handle, HWND_TOPMOST, 0, 0, 0, 0, flags)
    user32.SetWindowPos(handle, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    # Then the keyboard focus, so keystrokes reach it: an Alt tap counts as
    # input, which unlocks SetForegroundWindow, and sharing the current
    # foreground thread's input state makes the switch allowed outright.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    foreground = user32.GetForegroundWindow()
    theirs = user32.GetWindowThreadProcessId(foreground, None)
    ours = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = theirs and theirs != ours and user32.AttachThreadInput(ours, theirs, True)
    try:
        user32.BringWindowToTop(handle)
        user32.SetForegroundWindow(handle)
    finally:
        if attached:
            user32.AttachThreadInput(ours, theirs, False)
    time.sleep(0.4)
