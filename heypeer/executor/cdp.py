"""Driving a Chromium page over the DevTools protocol, step by step.

For screens where a fixed sequence beats an agent. Hermes drives a page by
writing JavaScript against it, and on Spotify that went wrong in ways no
prompt fixed: React inputs ignore values set from script, so renaming a
playlist took it ten minutes of retries, and its typed searches piled up in
the search box. Real input events - a mouse press at a point, text inserted
as if typed - are what a person does, and React sees them like one.

Chrome serves the protocol with --remote-debugging-port, and so does the
Spotify desktop app, which is Chromium underneath (see spotify_app.py).
"""

import json
import time

# Long enough for a page that is busy rendering, short enough that a dead
# connection is noticed within a step.
CALL_TIMEOUT_SECONDS = 20.0


class CdpError(RuntimeError):
    """The page did not answer, or did not have what was asked for."""


def page_target(port: int, url_part: str = "") -> dict:
    """The first page on the port whose URL contains `url_part`."""
    import requests

    targets = requests.get(f"http://127.0.0.1:{port}/json", timeout=3).json()
    for target in targets:
        if target.get("type") == "page" and url_part in target.get("url", ""):
            return target
    raise CdpError(f"no page with {url_part!r} on port {port}")


class Page:
    """One page's connection: evaluate script, and press, type and click like a user."""

    def __init__(self, port: int, url_part: str = ""):
        import websocket

        target = page_target(port, url_part)
        self.ws = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=CALL_TIMEOUT_SECONDS,
            suppress_origin=True)
        self._id = 0

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def call(self, method: str, **params) -> dict:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self._id:
                if "error" in message:
                    raise CdpError(f"{method}: {message['error']}")
                return message.get("result", {})

    def js(self, expression: str):
        """The value of `expression`, awaiting it if it is a promise."""
        result = self.call("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise CdpError(result["exceptionDetails"].get("exception", {})
                           .get("description", "script error"))
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout: float = 10.0, interval: float = 0.25):
        """Polls `expression` until it is truthy, and returns it."""
        deadline = time.monotonic() + timeout
        while True:
            value = self.js(expression)
            if value:
                return value
            if time.monotonic() > deadline:
                raise CdpError(f"timed out waiting for {expression[:80]!r}")
            time.sleep(interval)

    def center(self, selector_js: str) -> "tuple[float, float]":
        """The middle of the element `selector_js` evaluates to, scrolled into view."""
        point = self.js(f"""(() => {{
            const el = {selector_js};
            if (!el) return null;
            el.scrollIntoView({{block: 'center'}});
            const r = el.getBoundingClientRect();
            return [r.x + r.width / 2, r.y + r.height / 2];
        }})()""")
        if not point:
            raise CdpError(f"nothing at {selector_js[:80]!r}")
        return point[0], point[1]

    def click_at(self, x: float, y: float, button: str = "left") -> None:
        self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y,
                      button=button, clickCount=1)

    def click(self, selector_js: str, button: str = "left") -> None:
        self.click_at(*self.center(selector_js), button=button)

    def type_text(self, text: str) -> None:
        self.call("Input.insertText", text=text)

    def key(self, key: str, code: str, key_code: int, modifiers: int = 0) -> None:
        """A key press; modifiers are CDP's bits - 2 is Ctrl."""
        for kind in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", type=kind, key=key, code=code,
                      windowsVirtualKeyCode=key_code, modifiers=modifiers)

    def select_all_and_delete(self) -> None:
        self.key("a", "KeyA", 65, modifiers=2)
        self.key("Delete", "Delete", 46)

    def enter(self) -> None:
        self.call("Input.dispatchKeyEvent", type="rawKeyDown", key="Enter",
                  code="Enter", windowsVirtualKeyCode=13)
        self.call("Input.dispatchKeyEvent", type="char", key="Enter", text="\r")
        self.call("Input.dispatchKeyEvent", type="keyUp", key="Enter",
                  code="Enter", windowsVirtualKeyCode=13)


def text_match_js(selector: str, *texts: str) -> str:
    """Script for the first `selector` element whose visible text is one of `texts`
    - the app's language decides which, so callers pass both."""
    wanted = json.dumps([t.lower() for t in texts])
    return (f"[...document.querySelectorAll({json.dumps(selector)})]"
            f".find(e => {wanted}.includes(e.innerText.trim().toLowerCase()))")
