"""A small always-on-top window showing Hey Peer's conversation live: a
pulsing orb that reacts to state and live mic level, above a scrolling
transcript — rendered as a real HTML/CSS/JS page (`webui/conversation.html`)
via `pywebview` (the OS's native web view — WebView2 on Windows, already
present on Windows 10/11, no extra runtime to ship) instead of a Tkinter
Canvas.

The first version of this window used Tkinter, which the user flagged as
looking dated and "not viable for a real product" — fair: Tk's default
widget styling is hard to make look modern. A real web page gets proper
CSS (gradients, blur/glassmorphism, transitions, animations) essentially
for free, while staying lightweight since it reuses the OS's own browser
engine rather than bundling one.

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


def _window_process(command_queue: "multiprocessing.Queue") -> None:
    """Runs in the child process: creates the window, then pumps `command_queue`
    (JS snippets to evaluate) via pywebview's own background-thread hook so its
    event loop still owns this process's main thread."""
    import webview

    window = webview.create_window(
        "Hey Peer",
        url=str(HTML_PATH),
        width=380,
        height=480,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
        resizable=False,
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

    webview.start(pump_commands, window)


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

    def log(self, message: str) -> None:
        self._send(f"log({json.dumps(message)})")

    def set_level(self, level: float) -> None:
        self._send(f"setLevel({float(max(0.0, min(1.0, level)))})")

    def set_state(self, state: str) -> None:
        self._send(f"setState({json.dumps(state)})")

    def close(self) -> None:
        self._send(None)
