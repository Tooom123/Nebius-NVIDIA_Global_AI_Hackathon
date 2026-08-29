"""A borderless animated blob that drops in from the top of the screen when
Hey Peer is activated, morphing organically and swelling with the user's
voice, then slides back up when the turn is over.

Rendered as an HTML page (`webui/conversation.html`) through `pywebview`
(the OS's native web view — WebView2 on Windows, already present on Windows
10/11), running in its own process.

## How the rectangle is actually removed

Four earlier attempts failed, each on a different wrong assumption, and the
history is worth keeping because the failure was subtle every time:

1. `shadow=False` + forcing `gui="edgechromium"`. Real issues (Windows draws
   a drop shadow behind frameless windows; the legacy MSHTML backend can't do
   transparency), but a rectangle remained.
2. A Win32 layered-window **color key**. Cannot work here at all: WebView2
   renders through DirectComposition into its own child surface, which the
   parent window's color-keying never sees.
3. pywebview's `transparent=True`, created non-hidden so its Show/Hide
   transparency hack isn't skipped. This *did* make WebView2 transparent —
   and revealed that `platforms/winforms.py` sets only the web view's
   background transparent, never the WinForms `Form` behind it, which keeps
   its default Control-grey. Hence "a grey rectangle".
4. `SetWindowRgn` with a fixed **ellipse**. Finally rectangle-free — a window
   region is applied by the window manager, so pixels outside it aren't part
   of the window whatever renders inside — but clipping an animated blob to a
   static circle looked, accurately, truncated.

What's here now keeps the region (the only mechanism that reliably works)
and fixes what made it ugly: the region is a **polygon recomputed every
frame from the blob's actual outline** (`blob_shape.blob_points`), not a
fixed ellipse. The page just paints a full-bleed gradient and never clips
anything; the region carves the silhouette out of it.

That inversion is the important part. Any design where CSS animates a shape
*and* a window region clips it has two independent notions of the outline
that inevitably disagree — whatever the region doesn't cover gets chopped,
whatever the page doesn't paint shows as grey. With the region as the sole
source of shape there is nothing to keep in sync, and no per-frame
JavaScript either: only a cheap local `CreatePolygonRgn` call.

It also restores a real size reaction to the voice, since `blob_points`
takes the mic level and the region follows it — the previous fixed-ellipse
version could only fake that with brightness.

## Why a separate process

A thread-based version hung the *entire interpreter* in this project's Linux
dev sandbox — `webview.create_window()` never returned and no other thread
progressed, consistent with the native call holding the GIL while stuck
(no GTK/WebKit backend there). Whether that can also happen on
Windows/WebView2 is unverified, but a hang that takes down all of Hey Peer
is worth guarding against regardless: `Process.start()` returns immediately
no matter what the child does.
"""

import json
import multiprocessing
import platform
import threading
import time
from pathlib import Path

from heypeer.tray.blob_shape import blob_points

HTML_PATH = Path(__file__).resolve().parent / "webui" / "conversation.html"

WINDOW_TITLE = "Hey Peer"
WINDOW_WIDTH = 210
WINDOW_HEIGHT = 210
TOP_MARGIN = 0  # resting position: flush with the top edge of the screen

# 3-degree steps around the outline: fine enough that the polygon region
# shows no facets at this size, still trivial to build every frame.
OUTLINE_POINTS = 120

FRAME_INTERVAL = 1 / 30
# Polling interval while nothing is on screen — the overwhelmingly common
# case, since the indicator only appears during an actual turn. Animating at
# frame rate then would burn CPU for nothing.
IDLE_POLL_INTERVAL = 0.1
# Exponential easing factor per frame for the slide in/out. Chosen over a
# fixed duration so an interrupted slide (state flipping mid-animation)
# simply retargets instead of jumping.
SLIDE_EASING = 0.22
SLIDE_SETTLED_PX = 2

# Only shown while a turn is actually happening — the indicator should appear
# when Hey Peer has heard something, not sit on screen permanently.
_VISIBLE_STATES = {"recording", "thinking", "speaking"}

# Below this change, a new level isn't worth a round trip into the page for
# its brightness reaction (the size reaction goes through the region, which
# is local and updated every frame regardless).
_LEVEL_JS_EPSILON = 0.06


def _set_window_region(title: str, points: "list[tuple[int, int]]") -> bool:
    """Windows-only: clips the window titled `title` to `points`, so it has
    no rectangular edge. Returns whether it was applied.

    Every win32 call gets explicit argtypes/restype — ctypes otherwise
    defaults them to 32-bit `c_int`, silently truncating 64-bit handles,
    which produced a real `OverflowError` crash elsewhere in this project
    (see `heypeer/tray/cursor.py`'s module docstring).

    Best-effort: a window that can't be found or clipped is a cosmetic
    problem, and crashing the indicator over it would be a worse one.
    """
    if platform.system() != "Windows":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    gdi32.CreatePolygonRgn.argtypes = [ctypes.POINTER(POINT), ctypes.c_int, ctypes.c_int]
    gdi32.CreatePolygonRgn.restype = wintypes.HRGN
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int

    try:
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        array = (POINT * len(points))(*[POINT(x, y) for x, y in points])
        region = gdi32.CreatePolygonRgn(array, len(points), 2)  # 2 = WINDING
        if not region:
            return False
        # Redraw only while visible: repainting on every frame of the
        # slide-out is wasted work the user never sees.
        user32.SetWindowRgn(hwnd, region, True)
        # Ownership of `region` passes to the window; it must not be deleted
        # here, and the system frees the previous one.
        return True
    except Exception:
        return False


def _window_process(command_queue: "multiprocessing.Queue") -> None:
    """Runs in the child process. Owns the window, the command pump, and the
    animation loop that drives the outline."""
    import webview

    shared = {"visible": False, "level": 0.0, "quit": False}

    x_position = 0
    try:
        x_position = max(0, (webview.screens[0].width - WINDOW_WIDTH) // 2)
    except Exception:
        pass  # screen info unavailable on this backend - fall back to the left edge

    offscreen_y = -WINDOW_HEIGHT - 20

    window = webview.create_window(
        WINDOW_TITLE,
        url=str(HTML_PATH),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        x=x_position,
        y=offscreen_y,
        frameless=True,
        easy_drag=False,  # the region makes the whole window the blob; dragging it would just move it off-place
        on_top=True,
        resizable=False,
        shadow=False,
        # Kept alongside the region: where it works it softens the edges,
        # and where it doesn't the region still removes the rectangle. NOT
        # combined with hidden=True, which would skip pywebview's own
        # transparency setup entirely (see module docstring).
        transparent=True,
    )

    def animate(_window) -> None:
        started_at = time.time()
        y = float(offscreen_y)
        on_screen = False
        last_js_level = -1.0

        while not shared["quit"]:
            if not on_screen and not shared["visible"]:
                # Nothing on screen: idle cheaply instead of waking 30x a
                # second to do nothing. This is the common case by far —
                # the indicator is only up during an actual turn.
                time.sleep(IDLE_POLL_INTERVAL)
                continue

            target_y = float(TOP_MARGIN if shared["visible"] else offscreen_y)

            if shared["visible"] and not on_screen:
                try:
                    _window.move(x_position, offscreen_y)
                    _window.show()
                except Exception:
                    pass
                y = float(offscreen_y)
                on_screen = True

            if on_screen:
                y += (target_y - y) * SLIDE_EASING
                if abs(target_y - y) < SLIDE_SETTLED_PX:
                    y = target_y

                level = shared["level"]
                points = blob_points(
                    WINDOW_WIDTH,
                    WINDOW_HEIGHT,
                    t=time.time() - started_at,
                    level=level,
                    n_points=OUTLINE_POINTS,
                )
                _set_window_region(WINDOW_TITLE, points)
                try:
                    _window.move(x_position, int(round(y)))
                except Exception:
                    pass

                if abs(level - last_js_level) >= _LEVEL_JS_EPSILON:
                    last_js_level = level
                    try:
                        _window.evaluate_js(f"setLevel({level})")
                    except Exception:
                        pass

                if not shared["visible"] and y == target_y:
                    try:
                        _window.hide()
                    except Exception:
                        pass
                    on_screen = False

            time.sleep(FRAME_INTERVAL)

    def pump_commands(_window) -> None:
        threading.Thread(target=animate, args=(_window,), daemon=True).start()
        while True:
            kind, payload = command_queue.get()
            try:
                if kind == "quit":
                    shared["quit"] = True
                    _window.destroy()
                    return
                if kind == "level":
                    shared["level"] = payload
                elif kind == "state":
                    shared["visible"] = payload in _VISIBLE_STATES
                    _window.evaluate_js(f"setState({json.dumps(payload)})")
            except Exception:
                pass  # window mid-close, page not ready yet, etc.

    # gui="edgechromium" forces the modern WebView2 backend rather than
    # letting pywebview fall back to the legacy MSHTML/IE engine, which
    # can't do transparency at all.
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
        self._send("level", float(max(0.0, min(1.0, level))))

    def set_state(self, state: str) -> None:
        """No-ops when the state hasn't changed. Called from the audio
        callback on every chunk (~12x/second), and each change drives a
        window transition."""
        if state == self._last_state:
            return
        self._last_state = state
        self._send("state", state)

    def close(self) -> None:
        self._send("quit")
