"""The Spotify and WhatsApp sequences, against a page that records what it is told."""

from unittest.mock import patch

from heypeer.executor import spotify_app, whatsapp_web


class FakePage:
    """Answers scripts by the first matching fragment in `answers`."""

    def __init__(self, answers: "list[tuple[str, object]]"):
        self.answers = answers
        self.actions: "list[tuple]" = []

    def js(self, expression: str):
        for fragment, value in self.answers:
            if fragment in expression:
                return value(expression) if callable(value) else value
        return None

    def wait_for(self, expression: str, timeout: float = 10.0, interval: float = 0.25):
        value = self.js(expression)
        if not value:
            raise RuntimeError("timed out")
        return value

    def click(self, selector_js: str, button: str = "left") -> None:
        self.actions.append(("click", selector_js, button))

    def type_text(self, text: str) -> None:
        self.actions.append(("type", text))

    def select_all_and_delete(self) -> None:
        self.actions.append(("clear",))

    def enter(self) -> None:
        self.actions.append(("enter",))

    def close(self) -> None:
        pass


def test_each_search_starts_from_an_empty_box() -> None:
    """Typed into as it was, the box ran every search together."""
    page = FakePage([(".length >", True), (".length", 0),
                     ("startsWith", True)])
    with patch("heypeer.executor.spotify_app.time.sleep"):
        assert spotify_app.add_track(page, "Teardrop", "Massive Attack")
    kinds = [a[0] for a in page.actions]
    assert kinds[:3] == ["click", "clear", "type"]
    assert page.actions[2] == ("type", "Teardrop Massive Attack")


def test_a_track_that_is_not_found_is_skipped() -> None:
    page = FakePage([])
    with patch("heypeer.executor.spotify_app.time.sleep"):
        assert not spotify_app.add_track(page, "Nope", "Nobody", log=lambda m: None)
    assert not any(a[0] == "click" and "add-to-playlist" in a[1] for a in page.actions)


def test_only_songs_are_added() -> None:
    """A podcast episode once slipped into the playlist."""
    page = FakePage([(".length >", True), (".length", 0),
                     ("startsWith", True)])
    with patch("heypeer.executor.spotify_app.time.sleep"):
        spotify_app.add_track(page, "Weightless", "Marconi Union")
    row_script = next(a[1] for a in page.actions if a[0] == "click" and "add-to-playlist" in a[1])
    assert "episode" in row_script


def test_five_tracks_and_no_more() -> None:
    added = []
    with patch("heypeer.executor.cdp.Page", return_value=FakePage([])), patch.object(
        spotify_app, "delete_playlists"), patch.object(
        spotify_app, "create_playlist", return_value="abc"), patch.object(
        spotify_app, "add_track", side_effect=lambda p, t, a, log: added.append(t) or t != "B"), \
            patch.object(spotify_app, "tracks", return_value=[]), \
            patch("heypeer.executor.spotify_app.time.sleep"):
        link, _ = spotify_app.make_playlist("Chill", [(t, "x") for t in "ABCDEFG"], log=lambda m: None)
    assert link == "https://open.spotify.com/playlist/abc"
    assert added == ["A", "B", "C", "D", "E", "F"], "B missed, so F made the fifth"


def test_the_old_playlist_goes_first() -> None:
    order = []
    with patch("heypeer.executor.cdp.Page", return_value=FakePage([])), patch.object(
        spotify_app, "delete_playlists", side_effect=lambda *a: order.append("delete")), patch.object(
        spotify_app, "create_playlist", side_effect=lambda *a: order.append("create") or "id"), \
            patch.object(spotify_app, "add_track", return_value=True), \
            patch.object(spotify_app, "tracks", return_value=[]), \
            patch("heypeer.executor.spotify_app.time.sleep"):
        spotify_app.make_playlist("Chill", [("A", "x")], log=lambda m: None)
    assert order == ["delete", "create"]


def _whatsapp(box_texts: "list[str]") -> FakePage:
    texts = iter(box_texts)
    return FakePage([("innerText.trim()", lambda e: next(texts)), ("", True)])


def test_a_chat_that_does_not_open_stops_the_message() -> None:
    page = FakePage([("#main header", False), ("", True)])
    with patch("heypeer.executor.cdp.Page", return_value=page), patch(
            "heypeer.executor.whatsapp_web.time.sleep"), patch.object(whatsapp_web, "_port", return_value=1):
        assert not whatsapp_web.write_message("Tally", "Hi", send=True, log=lambda m: None)
    assert ("type", "Hi") not in page.actions


def test_the_chat_box_is_emptied_before_typing() -> None:
    """A rehearsal left the last run's message, with a dead link, in the box."""
    page = _whatsapp(["", "Hi"])
    with patch("heypeer.executor.cdp.Page", return_value=page), patch(
            "heypeer.executor.whatsapp_web.time.sleep"), patch.object(whatsapp_web, "_port", return_value=1):
        assert whatsapp_web.write_message("Tally", "Hi", send=False, log=lambda m: None)
    assert page.actions[-2:] == [("clear",), ("type", "Hi")]


def test_a_box_that_will_not_empty_stops_the_message() -> None:
    page = _whatsapp(["old message"])
    with patch("heypeer.executor.cdp.Page", return_value=page), patch(
            "heypeer.executor.whatsapp_web.time.sleep"), patch.object(whatsapp_web, "_port", return_value=1):
        assert not whatsapp_web.write_message("Tally", "Hi", send=True, log=lambda m: None)
    assert ("type", "Hi") not in page.actions


def test_a_real_run_sends() -> None:
    page = _whatsapp(["", "Hi"])
    with patch("heypeer.executor.cdp.Page", return_value=page), patch(
            "heypeer.executor.whatsapp_web.time.sleep"), patch.object(whatsapp_web, "_port", return_value=1):
        assert whatsapp_web.write_message("Tally", "Hi", send=True, log=lambda m: None)
    assert page.actions[-1] == ("enter",)
