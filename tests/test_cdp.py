"""The DevTools connection itself, against a socket that records what it is sent."""

import json
from unittest.mock import MagicMock, patch

import pytest

from heypeer.executor import cdp


class FakeSocket:
    """Replies to each call with `reply(message)`, after any queued events."""

    def __init__(self, reply=lambda m: {"result": {}}, events=()):
        self.reply = reply
        self.events = list(events)
        self.sent: "list[dict]" = []
        self._inbox: "list[str]" = []
        self.closed = False

    def send(self, data: str) -> None:
        message = json.loads(data)
        self.sent.append(message)
        self._inbox.extend(json.dumps(e) for e in self.events)
        self._inbox.append(json.dumps({"id": message["id"], **self.reply(message)}))

    def recv(self) -> str:
        return self._inbox.pop(0)

    def close(self) -> None:
        self.closed = True


def _page(socket: FakeSocket) -> cdp.Page:
    page = cdp.Page.__new__(cdp.Page)
    page.ws = socket
    page._id = 0
    return page


def _evaluates_to(value):
    return lambda m: {"result": {"result": {"value": value}}}


def test_a_call_returns_its_own_answer_past_events() -> None:
    """Chrome interleaves events with answers; only the matching id counts."""
    socket = FakeSocket(lambda m: {"result": {"ok": m["id"]}},
                        events=[{"method": "Page.loadEventFired", "params": {}}])
    assert _page(socket).call("Page.enable") == {"ok": 1}


def test_each_call_gets_a_new_id() -> None:
    socket = FakeSocket()
    page = _page(socket)
    page.call("A")
    page.call("B")
    assert [m["id"] for m in socket.sent] == [1, 2]


def test_a_protocol_error_is_raised() -> None:
    socket = FakeSocket(lambda m: {"error": {"message": "No node"}})
    with pytest.raises(cdp.CdpError, match="DOM.focus"):
        _page(socket).call("DOM.focus")


def test_js_returns_the_value_and_awaits_promises() -> None:
    socket = FakeSocket(_evaluates_to(42))
    assert _page(socket).js("6 * 7") == 42
    params = socket.sent[0]["params"]
    assert params["returnByValue"] and params["awaitPromise"]


def test_a_script_exception_is_raised() -> None:
    socket = FakeSocket(lambda m: {"result": {"exceptionDetails": {
        "exception": {"description": "TypeError: x is null"}}}})
    with pytest.raises(cdp.CdpError, match="TypeError"):
        _page(socket).js("x.y")


def test_wait_for_returns_the_first_truthy_value() -> None:
    values = iter([None, 0, "ready"])
    socket = FakeSocket(lambda m: _evaluates_to(next(values))(m))
    with patch("heypeer.executor.cdp.time.sleep"):
        assert _page(socket).wait_for("state") == "ready"


def test_wait_for_gives_up_at_the_deadline() -> None:
    socket = FakeSocket(_evaluates_to(False))
    clock = iter([0.0, 5.0, 11.0])
    with patch("heypeer.executor.cdp.time.monotonic", side_effect=lambda: next(clock)), \
            patch("heypeer.executor.cdp.time.sleep"):
        with pytest.raises(cdp.CdpError, match="timed out"):
            _page(socket).wait_for("never", timeout=10)


def test_center_of_a_missing_element_is_an_error() -> None:
    socket = FakeSocket(_evaluates_to(None))
    with pytest.raises(cdp.CdpError, match="nothing at"):
        _page(socket).center("document.querySelector('#gone')")


def test_a_click_moves_then_presses_then_releases() -> None:
    """React ignores a press with no move before it."""
    socket = FakeSocket(lambda m: _evaluates_to([100, 50])(m) if m["method"] == "Runtime.evaluate"
                        else {"result": {}})
    _page(socket).click("document.body")
    mouse = [m["params"] for m in socket.sent if m["method"] == "Input.dispatchMouseEvent"]
    assert [p["type"] for p in mouse] == ["mouseMoved", "mousePressed", "mouseReleased"]
    assert all((p["x"], p["y"]) == (100, 50) for p in mouse)


def test_a_right_click_says_so() -> None:
    socket = FakeSocket()
    _page(socket).click_at(1, 2, button="right")
    pressed = next(m["params"] for m in socket.sent if m["params"].get("type") == "mousePressed")
    assert pressed["button"] == "right"


def test_text_is_inserted_as_typed() -> None:
    socket = FakeSocket()
    _page(socket).type_text("Teardrop Massive Attack")
    assert socket.sent == [{"id": 1, "method": "Input.insertText",
                            "params": {"text": "Teardrop Massive Attack"}}]


def test_select_all_holds_ctrl_and_delete_does_not() -> None:
    socket = FakeSocket()
    _page(socket).select_all_and_delete()
    keys = [(m["params"]["key"], m["params"]["modifiers"]) for m in socket.sent]
    assert keys == [("a", 2), ("a", 2), ("Delete", 0), ("Delete", 0)]


def test_enter_sends_a_character_between_down_and_up() -> None:
    """Without the char event a chat box sees the key but sends nothing."""
    socket = FakeSocket()
    _page(socket).enter()
    kinds = [m["params"]["type"] for m in socket.sent]
    assert kinds == ["rawKeyDown", "char", "keyUp"]
    assert socket.sent[1]["params"]["text"] == "\r"


def test_closing_twice_is_harmless() -> None:
    socket = FakeSocket()
    socket.close = MagicMock(side_effect=[None, OSError("already closed")])
    page = _page(socket)
    page.close()
    page.close()


def test_the_page_is_found_by_url_and_type() -> None:
    targets = [{"type": "service_worker", "url": "https://web.whatsapp.com/sw.js"},
               {"type": "page", "url": "https://open.spotify.com/"},
               {"type": "page", "url": "https://web.whatsapp.com/"}]
    response = MagicMock()
    response.json.return_value = targets
    with patch("requests.get", return_value=response):
        assert cdp.page_target(9222, "web.whatsapp.com") is targets[2]


def test_no_matching_page_is_an_error() -> None:
    response = MagicMock()
    response.json.return_value = [{"type": "page", "url": "about:blank"}]
    with patch("requests.get", return_value=response):
        with pytest.raises(cdp.CdpError, match="whatsapp"):
            cdp.page_target(9222, "whatsapp")


def test_text_match_ignores_case_and_accepts_either_language() -> None:
    script = cdp.text_match_js("button", "Create", "Créer")
    assert json.dumps(["create", "créer"]) in script
    assert "toLowerCase()" in script


def test_text_match_quotes_the_selector_safely() -> None:
    script = cdp.text_match_js("button[aria-label=\"Add\"]", "Add")
    assert json.dumps("button[aria-label=\"Add\"]") in script
