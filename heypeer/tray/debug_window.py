"""A minimal always-on-top indicator: a small circle that appears flush
against the top edge of the screen the instant "Hey Peer" is detected —
staying hidden the rest of the time — pulsing/waving to show Hey Peer's
state and live mic level. Rendered as a real HTML/CSS/JS page
(`webui/conversation.html`) via `pywebview` (the OS's native web view —
WebView2 on Windows, already present on Windows 10/11, no extra runtime to
ship) instead of a Tkinter Canvas.

Deliberately just the orb — no chat window, no transcript. Two design
changes drove this: the user first flagged the original Tkinter window as
looking dated and "not viable for a real product" (fair: Tk's default widget
styling is hard to make look modern), and then explicitly asked to drop the
conversation transcript entirely and keep only the circle, since the actual
conversation is easier to follow in the terminal log anyway (see
`HeyPeer._log`, which just prints - no `debug_window.log()` any more).

The window only shows itself while a turn is actually happening (recording/
thinking/speaking) — hidden while idle/listening — per explicit feedback
that a wake-word engine (à la Siri) should surface *when it's actually
heard something*, not sit there all the time. `set_state()` below drives
`window.show()`/`window.hide()`, not just the CSS.

Real bug reported after this rendered on actual Windows hardware, in two
rounds: first "a square persists around" the circle, which `shadow=False`
(disables Windows' native drop shadow behind frameless windows) and forcing
`gui="edgechromium"` (avoids a silent fallback to the legacy MSHTML/IE
backend, which doesn't support transparency at all) were meant to fix — but
a white rectangle was still visible afterwards. Rather than keep
special-casing pywebview's own `transparent` support (version- and
backend-dependent, and evidently still not reliable even with both of the
above), this now bypasses it entirely: the page renders on a solid "magic
pink" background (`MAGIC_BACKGROUND_CSS`) and, once loaded,
`_make_colorkey_transparent` applies the classic Win32 layered-window
color-key technique directly (`SetLayeredWindowAttributes` with
`LWA_COLORKEY`) — every pixel matching that exact color becomes fully
transparent/click-through, independent of whatever pywebview's own
transparency flag does. Same technique many Windows overlay/widget apps use
for non-rectangular windows. `transparent=True` is no longer passed to
`create_window` to avoid pywebview applying its own (possibly conflicting)
layered-window attributes first.

Runs in its own **process**, not a thread. A thread-based version was tried
first and, in this project's Linux dev sandbox, `webview.create_window()`
hung the *entire interpreter* — including unrelated threads — apparently
because the native call never releases the GIL while stuck (no GTK/WebKit
backend available there). Whether that specific failure mode can also
happen on Windows/WebView2 is unverified, but a full-process hang taking
down all of Hey Peer with it is bad enough to guard against regardless:
`multiprocessing.Process.start()` returns to the caller almost immediately
no matter what the child ends up doing, so the main app can never be stuck
waiting on this window.
"""

import json
import multiprocessing
import platform
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent / "webui" / "conversation.html"

WINDOW_TITLE = "Hey Peer"
WINDOW_WIDTH = 200
WINDOW_HEIGHT = 170  # tall enough for the wave rings' peak scale without clipping
TOP_MARGIN = 0  # flush with the screen's top edge - the orb reads as "emerging from" it

# Must match `webui/conversation.html`'s `html, body { background: ... }`
# exactly - every pixel this color becomes fully transparent/click-through.
# Chosen because none of the orb's own accent colors (blues/greens/purples/
# a pink that's close but not identical) are pure magenta.
MAGIC_BACKGROUND_CSS = "#ff00ff"
MAGIC_BACKGROUND_COLORREF = 0x00FF00FF  # COLORREF is 0x00BBGGRR - symmetric for #ff00ff

# Only shown (see `DebugWindow.set_state`) while a turn is actually active -
# hidden the rest of the time, per explicit feedback that the indicator
# should appear on detection, not sit there continuously.
_VISIBLE_STATES = {"recording", "thinking", "speaking"}


def _make_colorkey_transparent(title: str) -> None:
    """Windows-only: makes every `MAGIC_BACKGROUND_COLORREF` pixel in the
    window titled `title` fully transparent, via the classic layered-window
    color-key technique — see module docstring for why this replaces
    relying on pywebview's own `transparent` flag. Every win32 call gets
    explicit argtypes/restype (see heypeer/tray/cursor.py's module docstring
    for why that matters — undeclared args silently truncate 64-bit
    handles). Best-effort: finding the window by title can only fail softly
    here (a plain rectangle beats crashing the whole indicator)."""
    if platform.system() != "Windows":
        return
    import ctypes
    from ctypes import wintypes

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    LWA_COLORKEY = 0x00000001

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD
    ]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL

    try:
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        user32.SetLayeredWindowAttributes(hwnd, MAGIC_BACKGROUND_COLORREF, 0, LWA_COLORKEY)
    except Exception:
        pass


def _window_process(command_queue: "multiprocessing.Queue") -> None:
    """Runs in the child process: creates the window, then pumps `command_queue`
    (show/hide/eval-JS commands) via pywebview's own background-thread hook so
    its event loop still owns this process's main thread."""
    import webview

    x, y = None, None  # None lets pywebview fall back to its own default placement
    try:
        screen = webview.screens[0]
        x = max(0, (screen.width - WINDOW_WIDTH) // 2)
        y = TOP_MARGIN
    except Exception:
        pass  # screen info unavailable on this backend - not worth failing window creation over

    window = webview.create_window(
        WINDOW_TITLE,
        url=str(HTML_PATH),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        x=x,
        y=y,
        frameless=True,
        easy_drag=True,
        on_top=True,
        resizable=False,
        shadow=False,
        hidden=True,  # starts hidden - only shown on an actual turn, see set_state
    )
    window.events.loaded += lambda *_a, **_k: _make_colorkey_transparent(WINDOW_TITLE)

    def pump_commands(_window) -> None:
        while True:
            kind, payload = command_queue.get()  # blocks until the next command
            try:
                if kind == "quit":
                    _window.destroy()
                    return
                elif kind == "show":
                    _window.show()
                elif kind == "hide":
                    _window.hide()
                elif kind == "eval":
                    _window.evaluate_js(payload)
            except Exception:
                pass  # window mid-close, page not ready yet, etc.

    # gui="edgechromium" forces the modern WebView2 backend rather than
    # letting pywebview silently fall back to the legacy MSHTML/IE engine if
    # backend auto-detection ever fails — MSHTML doesn't support
    # transparency at all, which would also produce an opaque rectangle.
    webview.start(pump_commands, window, gui="edgechromium")


class DebugWindow:
    def __init__(self) -> None:
        self._queue: multiprocessing.Queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_window_process, args=(self._queue,), daemon=True
        )
        self._process.start()

    def _send(self, kind: str, payload=None) -> None:
        try:
            self._queue.put((kind, payload))
        except Exception:
            pass  # queue closed / process gone — never let a UI hiccup break the app

    def set_level(self, level: float) -> None:
        self._send("eval", f"setLevel({float(max(0.0, min(1.0, level)))})")

    def set_state(self, state: str) -> None:
        self._send("eval", f"setState({json.dumps(state)})")
        self._send("show" if state in _VISIBLE_STATES else "hide")

    def close(self) -> None:
        self._send("quit")
