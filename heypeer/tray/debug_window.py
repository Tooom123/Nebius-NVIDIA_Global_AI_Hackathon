"""A minimal always-on-top indicator: a small circle that sits flush against
the top edge of the screen, pulsing/waving to show Hey Peer's state and live
mic level — rendered as a real HTML/CSS/JS page (`webui/conversation.html`)
via `pywebview` (the OS's native web view — WebView2 on Windows, already
present on Windows 10/11, no extra runtime to ship) instead of a Tkinter
Canvas.

Deliberately just the orb — no chat window, no transcript. Two design
changes drove this: the user first flagged the original Tkinter window as
looking dated and "not viable for a real product" (fair: Tk's default widget
styling is hard to make look modern), and then explicitly asked to drop the
conversation transcript entirely and keep only the circle, since the actual
conversation is easier to follow in the terminal log anyway (see
`HeyPeer._log`, which just prints - no `debug_window.log()` any more).

Real bug reported after this rendered on actual Windows hardware: "a square
persists around" the circle instead of a borderless orb. Windows' DWM draws
a native drop shadow behind frameless windows by default, which reads as a
rectangular halo around anything smaller/transparent inside it — pywebview
exposes `shadow=False` on `create_window` specifically to disable this, now
passed here. `webview.start()` is also given `gui="edgechromium"` explicitly,
so if backend auto-detection ever silently fell back to the legacy MSHTML/IE
engine (which doesn't support `transparent` at all and would paint an opaque
rectangle — also consistent with the reported symptom), it now fails loudly
instead of degrading quietly.

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
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent / "webui" / "conversation.html"


WINDOW_WIDTH = 200
WINDOW_HEIGHT = 170  # tall enough for the wave rings' peak scale without clipping
TOP_MARGIN = 0  # flush with the screen's top edge - the orb reads as "emerging from" it


def _window_process(command_queue: "multiprocessing.Queue") -> None:
    """Runs in the child process: creates the window, then pumps `command_queue`
    (JS snippets to evaluate) via pywebview's own background-thread hook so its
    event loop still owns this process's main thread."""
    import webview

    x, y = None, None  # None lets pywebview fall back to its own default placement
    try:
        screen = webview.screens[0]
        x = max(0, (screen.width - WINDOW_WIDTH) // 2)
        y = TOP_MARGIN
    except Exception:
        pass  # screen info unavailable on this backend - not worth failing window creation over

    window = webview.create_window(
        "Hey Peer",
        url=str(HTML_PATH),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        x=x,
        y=y,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
        resizable=False,
        shadow=False,
    )

    def pump_commands(_window) -> None:
        while True:
            js = command_queue.get()  # blocks until the next command or sentinel
            if js is None:
                _window.destroy()
                return
            try:
                _window.evaluate_js(js)
            except Exception:
                pass  # window mid-close, page not ready yet, etc.

    # gui="edgechromium" forces the modern WebView2 backend rather than
    # letting pywebview silently fall back to the legacy MSHTML/IE engine if
    # backend auto-detection ever fails — MSHTML doesn't support
    # `transparent` at all and would paint an opaque rectangle, which is
    # plausibly why an earlier run showed "a square" around the circle
    # instead of a borderless orb. Forcing this fails loudly (ImportError/
    # a missing-WebView2-runtime error) instead of silently degrading.
    webview.start(pump_commands, window, gui="edgechromium")


class DebugWindow:
    def __init__(self) -> None:
        self._queue: multiprocessing.Queue = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_window_process, args=(self._queue,), daemon=True
        )
        self._process.start()

    def _send(self, js: str) -> None:
        try:
            self._queue.put(js)
        except Exception:
            pass  # queue closed / process gone — never let a UI hiccup break the app

    def set_level(self, level: float) -> None:
        self._send(f"setLevel({float(max(0.0, min(1.0, level)))})")

    def set_state(self, state: str) -> None:
        self._send(f"setState({json.dumps(state)})")

    def close(self) -> None:
        self._send(None)
