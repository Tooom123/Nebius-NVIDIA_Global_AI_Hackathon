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

Getting the window to render as *just the blob* — no rectangle around it —
took three attempts, the first two of which were wrong for reasons worth
recording:

1. `shadow=False` + forcing `gui="edgechromium"`. Addressed real things
   (Windows draws a native drop shadow behind frameless windows; the legacy
   MSHTML backend can't do transparency at all) but a rectangle remained.
2. A Win32 layered-window color key (`SetLayeredWindowAttributes` with
   `LWA_COLORKEY`) over a solid-color page background. This *cannot* work
   here: WebView2 renders through DirectComposition into its own child
   surface, which the parent window's layered color-keying never sees. It's
   the right technique for a plain GDI window and the wrong one for a
   hardware-composited web view.
3. What's here now — pywebview's own `transparent=True`, which reading its
   source (`platforms/winforms.py`, `platforms/edgechromium.py` in 6.2.1)
   shows *is* properly implemented for EdgeChromium: it sets the WebView2
   controller's `DefaultBackgroundColor` to `Color.Transparent` and runs a
   Show/Hide dance to make it take effect.

The reason attempt 3 hadn't been tried successfully before is a genuine
conflict with `hidden=True`, visible in that same source as an `if/elif`:

    if window.hidden:            # our old case - transparency hack skipped
        ...
    elif window.transparent and is_chromium:
        browser.Show(); browser.Hide()   # the hack that makes it work

Passing `hidden=True` therefore silently disabled the very transparency
setup we needed. So the window is now created *not* hidden (letting that
path run) and hidden immediately afterwards from the command pump instead.

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
import time
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent / "webui" / "conversation.html"

WINDOW_TITLE = "Hey Peer"
WINDOW_WIDTH = 190
WINDOW_HEIGHT = 190  # room for the blob at its peak level-driven scale
TOP_MARGIN = 0  # flush with the screen's top edge - the blob drops in from above it

# How long the page's slide-out animation takes - the window is only really
# hidden after this, so the animation is actually seen instead of the window
# vanishing mid-transition. Must stay >= the CSS transition duration.
HIDE_ANIMATION_SECONDS = 0.55

# Grace period before hiding the window at startup: pywebview's transparency
# path shows the window itself (on the navigation-start event), so hiding it
# too eagerly races that and can leave it stuck visible.
STARTUP_HIDE_DELAY_SECONDS = 1.0

# Only shown (see `DebugWindow.set_state`) while a turn is actually active -
# hidden the rest of the time, per explicit feedback that the indicator
# should appear on detection, not sit there continuously.
_VISIBLE_STATES = {"recording", "thinking", "speaking"}


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
        # Deliberately NOT hidden=True: that would skip pywebview's
        # transparency setup entirely (see module docstring). The window is
        # hidden from the pump below instead.
        transparent=True,
    )

    def pump_commands(_window) -> None:
        # Start hidden, but only after pywebview's own transparency
        # show/hide dance has settled - see STARTUP_HIDE_DELAY_SECONDS.
        time.sleep(STARTUP_HIDE_DELAY_SECONDS)
        try:
            _window.hide()
        except Exception:
            pass

        while True:
            kind, payload = command_queue.get()  # blocks until the next command
            try:
                if kind == "quit":
                    _window.destroy()
                    return
                elif kind == "show":
                    # Window first, then the slide-in - the reverse order
                    # would start the animation on a window nobody can see.
                    _window.show()
                    _window.evaluate_js("setVisible(true)")
                elif kind == "hide":
                    # Slide out first and only actually hide once it's had
                    # time to play, otherwise the window just vanishes.
                    _window.evaluate_js("setVisible(false)")
                    time.sleep(HIDE_ANIMATION_SECONDS)
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
        self._last_state: str | None = None

    def _send(self, kind: str, payload=None) -> None:
        try:
            self._queue.put((kind, payload))
        except Exception:
            pass  # queue closed / process gone — never let a UI hiccup break the app

    def set_level(self, level: float) -> None:
        self._send("eval", f"setLevel({float(max(0.0, min(1.0, level)))})")

    def set_state(self, state: str) -> None:
        """No-ops when the state hasn't actually changed. This is called from
        the audio callback on every chunk (~12x/second), and each show/hide
        drives a real window transition — one of which deliberately sleeps
        through its slide-out animation — so forwarding unchanged states
        would swamp the queue and stutter the animation."""
        if state == self._last_state:
            return
        self._last_state = state
        self._send("eval", f"setState({json.dumps(state)})")
        self._send("show" if state in _VISIBLE_STATES else "hide")

    def close(self) -> None:
        self._send("quit")
