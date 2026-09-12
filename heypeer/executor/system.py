"""System-level control that has nothing to do with a specific file or
app: volume, screen brightness, and other windows on the desktop.

Everything here is Windows-only and degrades to a harmless no-op (volume,
window control) or an honest failure the caller speaks aloud (brightness)
on any other platform - the dev sandbox this project has been built in is
Linux, so every ctypes/subprocess call is guarded behind `sys.platform ==
"win32"` and never actually reached here. What *is* independently testable
from a non-Windows machine is factored out on purpose: `_match_window`
takes a plain list of `(hwnd, title)` pairs rather than calling `EnumWindows`
itself, so the matching logic (does "Chrome" find "facture.pdf - Google
Chrome"?) has real test coverage even though the enumeration around it does
not - the same split `apps._find_start_menu_shortcut` uses for the Start
Menu search.

## Volume and window control: multimedia keys and Win32, not a new library

Volume up/down/mute are the same three multimedia keys a physical keyboard
sends (`VK_VOLUME_UP`/`_DOWN`/`_MUTE`), pressed via `keybd_event` - the exact
mechanism `executor/spotify.py`'s `press_play` already uses for the play/
pause key. One press moves the OS's own volume step (small, a couple of
percent on most default configurations); several are sent per command so
"baisse le son" is actually audible. There is no simple synchronous "set
volume to exactly N%" this way - that needs the Core Audio API (`pycaw` or
raw COM), a real dependency this project has stayed light on, for precision
a spoken "baisse le son" does not obviously need anyway.

Window control (maximize/minimize/close one app's window, or minimize
everything) is plain `user32.dll` - `EnumWindows` to find a window, `ShowWindow`
to change its state, `PostMessageW(WM_CLOSE)` to close one without blocking on
whatever the app does in response. `pywin32` was deliberately not added for
this: the project already talks to `user32`/`gdi32` directly via `ctypes` for
the layered-window overlay and the wake-word listener's keybd_event calls, so
this follows the same, already-established pattern rather than adding a new
one.

## Brightness: the one thing here that is genuinely uncertain

Screen brightness only has a software API (`WmiMonitorBrightnessMethods`,
under the `root/wmi` namespace) for a laptop's own integrated panel, driven
by its ACPI backlight control. Most **external desktop monitors** do not
expose brightness this way at all - they need DDC/CI, a different,
hardware-dependent protocol most Windows installs have no driver for out of
the box. This code cannot tell which situation it is in from here, and
should not pretend to: `adjust_brightness` returns whether it actually
changed anything, and the caller turns a `False` into an honest spoken
"je ne peux pas régler la luminosité", never a silent no-op reported as
success.
"""

import subprocess
import sys
import unicodedata

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
_KEYEVENTF_KEYUP = 0x0002

# One press moves the OS's own volume step, which is small on most default
# configurations (often ~2%) - several presses make "baisse le son" actually
# perceptible rather than nearly silent.
VOLUME_STEP_PRESSES = 4

# How much a single "monte/baisse la luminosité" changes brightness by, in
# the 0-100 scale WMI itself reports and accepts.
BRIGHTNESS_STEP = 15

SW_MAXIMIZE = 3
SW_MINIMIZE = 6
WM_CLOSE = 0x0010


def _press_key(vk: int) -> None:
    if sys.platform != "win32":
        return
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def volume_up() -> None:
    for _ in range(VOLUME_STEP_PRESSES):
        _press_key(VK_VOLUME_UP)


def volume_down() -> None:
    for _ in range(VOLUME_STEP_PRESSES):
        _press_key(VK_VOLUME_DOWN)


def volume_mute_toggle() -> None:
    """A single press - this is the OS's own mute *toggle*, so pressing it
    more than once would just undo itself."""
    _press_key(VK_VOLUME_MUTE)


def _run_powershell(script: str) -> "str | None":
    """Runs `script` and returns its stdout, or None on any failure at all -
    missing powershell.exe, no WMI namespace, a monitor with no software
    brightness control. A brightness change failing must degrade to a
    spoken message, never a traceback."""
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            # Explicit, because Python defaults to the console's
            # locale encoding - cp1252 on a French Windows - and
            # that raises UnicodeDecodeError on any byte above
            # 0x7f. Seen for real: a subprocess reader thread died
            # on 0x8f mid-output, losing the rest of the result.
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        )
    except Exception:
        return None
    output = result.stdout.strip()
    return output or None


def adjust_brightness(direction: str) -> bool:
    """`direction`: "up" or "down". Returns whether it actually changed
    something - see the module docstring for why this can genuinely fail on
    ordinary, correctly-working hardware (an external monitor)."""
    delta = BRIGHTNESS_STEP if direction == "up" else -BRIGHTNESS_STEP
    script = (
        "$m = Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness; "
        "$b = Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods; "
        f"$new = [Math]::Max(0, [Math]::Min(100, [int]$m.CurrentBrightness + ({delta}))); "
        "$b.WmiSetBrightness(1, $new); "
        "Write-Output $new"
    )
    return _run_powershell(script) is not None


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _list_windows() -> "list[tuple[int, str]]":
    """`[(hwnd, title), ...]` for every visible top-level window with a
    non-empty title. Windows-only; `[]` everywhere else."""
    if sys.platform != "win32":
        return []
    import ctypes

    user32 = ctypes.windll.user32
    results: "list[tuple[int, str]]" = []
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        results.append((hwnd, buf.value))
        return True

    user32.EnumWindows(enum_proc_type(callback), 0)
    return results


def _match_window(windows: "list[tuple[int, str]]", name_candidates: "list[str]") -> "int | None":
    """The hwnd of the window whose title best matches one of
    `name_candidates` (an app's name and aliases), or None.

    Substring, not exact: a real window title is rarely just the bare app
    name ("facture.pdf - Google Chrome", not "Chrome") - and declining beats
    guessing here too, since a match closes or resizes something.
    """
    normalised = [_normalise(n) for n in name_candidates if n]
    for hwnd, title in windows:
        title_norm = _normalise(title)
        if any(n in title_norm for n in normalised):
            return hwnd
    return None


def _resolve_window(app_name: str) -> "int | None":
    """The window `app_name` refers to, going through the same app registry
    `open_app` does (`resolve_app`) rather than matching an arbitrary window
    title freely - consistent with the rest of this project's "decline
    rather than guess" stance, and it means "minimise Chrome" and "ouvre
    Chrome" agree on what "Chrome" means."""
    from heypeer.executor.apps import resolve_app

    app = resolve_app(app_name)
    if app is None:
        return None
    return _match_window(_list_windows(), [app.name, *app.aliases])


def maximize_window(app_name: str) -> bool:
    return _set_window_state(app_name, SW_MAXIMIZE)


def minimize_window(app_name: str) -> bool:
    return _set_window_state(app_name, SW_MINIMIZE)


def _set_window_state(app_name: str, show_command: int) -> bool:
    if sys.platform != "win32":
        return False
    hwnd = _resolve_window(app_name)
    if hwnd is None:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, show_command)
    user32.SetForegroundWindow(hwnd)
    return True


def close_window(app_name: str) -> bool:
    """Asks the window to close - `PostMessageW`, not `SendMessageW`: this
    must not block waiting for whatever the app does with the message (a
    save-changes prompt, its own shutdown sequence), only hand it off."""
    if sys.platform != "win32":
        return False
    hwnd = _resolve_window(app_name)
    if hwnd is None:
        return False
    import ctypes

    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return True


def minimize_all() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    user32 = ctypes.windll.user32
    for hwnd, _title in _list_windows():
        user32.ShowWindow(hwnd, SW_MINIMIZE)
