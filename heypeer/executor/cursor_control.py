"""Delivering a real mouse click, on Windows.

The half of the visible cursor that actually presses something. The pointer
drawn by `tray/cursor_render.py` is a picture in a click-through overlay -
it cannot press anything by itself, and deliberately so: the overlay exists
precisely to let clicks pass through to what is underneath.

## Why SendInput, and not SetCursorPos plus mouse_event

`mouse_event` is the old API and is documented as superseded; `SendInput`
is what Windows wants used, it delivers press and release as one atomic
batch, and it goes through the same injection path as a real mouse so
applications that check for synthetic input see one consistent story rather
than a teleporting cursor followed by an unrelated button event.

## Why the real cursor moves at all

It has to. A click is delivered wherever the system pointer is, so pressing
a button means the pointer is there for that instant. What this module does
*not* do is animate the journey - the drawn pixel cursor does that, and the
real pointer jumps once, at the end, for the press itself.

That is also why `click_at` restores the user's pointer afterwards. They
were in the middle of something; borrowing their cursor for a few
milliseconds is acceptable, keeping it is not.

## What is verified from here, and what is not

Nothing about the actual clicking. There is no Windows in this project's
dev sandbox, so the ctypes structures and the call sequence below are
written from Microsoft's documentation and unit-tested against a mocked
`ctypes.windll`. Whether a real button depresses on real hardware is for
the manual test plan. `is_supported()` is real.
"""

import ctypes
import platform
import time

# SendInput's INPUT type for a mouse event, and the flags for the two
# transitions plus absolute positioning.
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

# SendInput's absolute coordinates are not pixels: the virtual desktop is
# mapped onto 0..65535 in each axis regardless of resolution.
ABSOLUTE_RANGE = 65535

# Between press and release. Zero works on most controls and fails on the
# ones that distinguish a click from a glitch; 40ms is comfortably a human
# click without being a noticeable delay.
CLICK_HOLD_SECONDS = 0.04

SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77


class ClickUnavailable(RuntimeError):
    """Clicking is not possible here - not Windows, or the call failed."""


def is_supported() -> bool:
    return platform.system() == "Windows"


class _MOUSEINPUT(ctypes.Structure):
    # dwExtraInfo is a pointer-sized field: declaring it as a plain int
    # truncates on 64-bit and corrupts the struct layout after it. This
    # project has already had one real crash from exactly that mistake in
    # win32 ctypes bindings - see tray/overlay.py's module docstring.
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    class _UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _UNION)]


def virtual_screen() -> "tuple[int, int, int, int]":
    """`(left, top, width, height)` of the whole virtual desktop.

    The whole desktop, not the primary monitor: absolute coordinates are
    relative to the virtual screen, so a second monitor to the left means
    negative pixel coordinates that still have to map into 0..65535.
    """
    user32 = ctypes.windll.user32
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def to_absolute(x: int, y: int, screen: "tuple[int, int, int, int]") -> "tuple[int, int]":
    """Pixel coordinates to SendInput's 0..65535 absolute space.

    Split out and pure so the arithmetic can be tested without Windows -
    it is the part most likely to be wrong, and the part whose wrongness
    would show up as clicking somewhere near but not on the target.
    """
    left, top, width, height = screen
    width = max(1, width)
    height = max(1, height)
    ax = round((x - left) * ABSOLUTE_RANGE / width)
    ay = round((y - top) * ABSOLUTE_RANGE / height)
    return (
        max(0, min(ABSOLUTE_RANGE, ax)),
        max(0, min(ABSOLUTE_RANGE, ay)),
    )


def cursor_position() -> "tuple[int, int]":
    """Where the system pointer is now - recorded before a click so it can
    be given back afterwards."""

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


def _send(flags: int, ax: int = 0, ay: int = 0) -> None:
    event = _INPUT(type=INPUT_MOUSE)
    event.mi = _MOUSEINPUT(dx=ax, dy=ay, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))
    if not sent:
        raise ClickUnavailable("SendInput delivered nothing")


def click_at(x: int, y: int, button: str = "left", restore: bool = True) -> None:
    """Clicks at screen pixel `(x, y)`.

    `restore` puts the user's pointer back where it was. On by default:
    they were in the middle of something, and an assistant that leaves the
    mouse somewhere else after every action is worse than one that cannot
    click at all.
    """
    if not is_supported():
        raise ClickUnavailable("clicking is only implemented for Windows")

    down, up = (
        (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
        if button == "right"
        else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    )

    previous = cursor_position() if restore else None
    screen = virtual_screen()
    ax, ay = to_absolute(x, y, screen)

    _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)
    _send(down)
    time.sleep(CLICK_HOLD_SECONDS)
    _send(up)

    if previous is not None:
        px, py = to_absolute(previous[0], previous[1], screen)
        _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, px, py)


def move_to(x: int, y: int) -> None:
    """Moves the system pointer without pressing anything. Not used by the
    animated cursor - that one draws itself and leaves the real pointer
    alone - but needed by anything that wants a hover."""
    if not is_supported():
        raise ClickUnavailable("moving the pointer is only implemented for Windows")
    ax, ay = to_absolute(x, y, virtual_screen())
    _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)
