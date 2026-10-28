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
    # An Alt tap counts as input, which is what unlocks SetForegroundWindow.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(handle)
    time.sleep(0.4)
