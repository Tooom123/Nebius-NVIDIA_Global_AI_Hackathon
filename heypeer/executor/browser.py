"""A Chrome window Hermes can drive with the user's own logins.

Hermes's browser tools launch a fresh, signed-out Chromium by default, which
cannot read anyone's inbox. They can instead attach to a running Chrome over
CDP - but Chrome refuses remote debugging on its default
profile, so this one runs on a profile of its own (`HEYPEER_BROWSER_PROFILE`),
signed in once by hand to whatever the tasks need. It then stays signed in
from one run to the next, beside the user's ordinary Chrome rather than
instead of it.

Hermes has to be told where it is in its own config, `browser.cdp_url:
http://127.0.0.1:9222` in config.yaml. An environment variable passed to
`hermes chat` does not reach it: the tools run in Hermes's long-lived
gateway process, which reads its config on every call but was started
with its own environment. Measured - with only the variable set, Hermes
logged a fresh Chromium and reported the inbox signed out.

The window is placed with `HEYPEER_BROWSER_POSITION` ("x,y"), so on a two-
screen machine it opens on the screen the audience is watching, and it is
brought to the front before each task so the audience sees the agent work.
"""

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

DEFAULT_PORT = 9222

CHROME_PATHS = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)

VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SW_MAXIMIZE = 3

# Chrome takes a few seconds to open its debugging port on a cold start.
START_TIMEOUT_SECONDS = 15.0


def cdp_url() -> "str | None":
    return os.environ.get("HEYPEER_BROWSER_CDP_URL") or None


def _port() -> int:
    url = cdp_url() or ""
    try:
        return int(url.rsplit(":", 1)[1].split("/")[0])
    except (IndexError, ValueError):
        return DEFAULT_PORT


def is_running() -> bool:
    """Whether a browser is answering on the debugging port."""
    try:
        with urllib.request.urlopen(  # noqa: S310 - localhost only
            f"http://127.0.0.1:{_port()}/json/version", timeout=1.5
        ):
            return True
    except Exception:
        return False


def _chrome() -> "Path | None":
    for raw in CHROME_PATHS:
        path = Path(os.path.expandvars(raw))
        if path.is_file():
            return path
    return None


def ensure_running(url: str = "about:blank") -> bool:
    """Starts the debugging Chrome if it is not already up, and returns
    whether it is. Does nothing, and returns False, when no CDP URL is
    configured - Hermes then uses its own browser, as before."""
    if cdp_url() is None:
        return False
    if is_running():
        return True
    chrome = _chrome()
    if chrome is None:
        return False
    profile = os.environ.get("HEYPEER_BROWSER_PROFILE") or str(
        Path.home() / "HeyPeerChrome"
    )
    args = [
        str(chrome),
        f"--remote-debugging-port={_port()}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    position = os.environ.get("HEYPEER_BROWSER_POSITION")
    if position:
        # A size rather than --start-maximized: combined with a position on
        # a secondary screen, Chrome honoured the position and ignored the
        # maximise, opening at half width.
        args += [f"--window-position={position}", "--window-size=1920,1080"]
    args.append(url)
    subprocess.Popen(args)  # noqa: S603 - our own fixed arguments
    deadline = time.time() + START_TIMEOUT_SECONDS
    while time.time() < deadline:
        if is_running():
            return True
        time.sleep(0.5)
    return False


def single_tab(url: str) -> bool:
    """Leaves the debugging Chrome with one tab, open on `url`.

    For the audience as much as for the agent: Hermes works in the current
    tab, and the window shows the current tab - so they had better be the
    same one. Left to itself it opened a fresh tab per action, nineteen in
    one task, while the window went on showing the first.
    """
    if not is_running():
        return False
    base = f"http://127.0.0.1:{_port()}"
    try:
        with urllib.request.urlopen(f"{base}/json/list", timeout=2) as response:  # noqa: S310
            old = [t["id"] for t in json.load(response) if t.get("type") == "page"]
        request = urllib.request.Request(f"{base}/json/new?{url}", method="PUT")
        with urllib.request.urlopen(request, timeout=5):  # noqa: S310
            pass
        for target in old:
            with urllib.request.urlopen(f"{base}/json/close/{target}", timeout=2):  # noqa: S310
                pass
        return True
    except Exception:
        return False


def bring_to_front() -> bool:
    """Raises the debugging Chrome above whatever is on its screen.

    DevTools' /json/activate only switches tabs - Windows does not let it
    take the foreground - so the window is found by its title, which
    Chrome makes from the active page's: DevTools says what that page is.
    When the user's own Chrome shows a page of the same name, the one on
    the stage side of the desktop wins.

    Raised with an Alt tap before SetForegroundWindow: Windows refuses the
    foreground to a process that has not had input recently, and silently -
    the call reports success and the window stays behind. Measured: plain
    SetActive left it under FL Studio; with the tap it comes up.
    """
    if not is_running():
        return False
    try:
        with urllib.request.urlopen(  # noqa: S310 - localhost only
            f"http://127.0.0.1:{_port()}/json/list", timeout=2
        ) as response:
            titles = [t.get("title", "") for t in json.load(response) if t.get("type") == "page"]
        import uiautomation as auto

        position = os.environ.get("HEYPEER_BROWSER_POSITION") or "0,0"
        stage_x = int(position.split(",")[0])
        candidates = [
            w for w in auto.GetRootControl().GetChildren()
            if w.ClassName == "Chrome_WidgetWin_1"
            and any(title and (w.Name or "").startswith(title) for title in titles)
        ]
        if not candidates:
            return False
        window = min(candidates, key=lambda w: abs(w.BoundingRectangle.left - stage_x))
        import ctypes

        user32 = ctypes.windll.user32
        handle = window.NativeWindowHandle
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.ShowWindow(handle, SW_MAXIMIZE)
        user32.SetForegroundWindow(handle)
        time.sleep(0.3)
        return True
    except Exception:
        return False
