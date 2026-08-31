"""Tests for playing something on Spotify.

Credentials are optional by design, so the two paths that matter are "a track
was resolved" and "one was not" - and the second must never be reported as
the first. Announcing music that is not playing is worse than admitting the
search only opened.
"""

from unittest.mock import MagicMock, patch

from heypeer.executor import spotify


def _api_response(items) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"tracks": {"items": items}}
    response.raise_for_status.return_value = None
    return response


TRACK = {
    "uri": "spotify:track:3IOQOtSaNBROSjjB65Uzcq",
    "name": "Alright",
    "artists": [{"name": "Kendrick Lamar"}],
}


def test_a_resolved_track_gives_both_what_to_play_and_what_to_say() -> None:
    """One search, two answers. Issuing a second request for the description
    would double the wait in front of someone who asked for music."""
    with (
        patch("heypeer.executor.spotify._access_token", return_value="tok"),
        patch("requests.get", return_value=_api_response([TRACK])) as get,
    ):
        track = spotify.find_track("Alright Kendrick Lamar", "id", "secret")

    assert track.uri == "spotify:track:3IOQOtSaNBROSjjB65Uzcq"
    assert track.spoken() == "Alright par Kendrick Lamar"
    assert get.call_count == 1


def test_a_track_is_named_the_way_the_user_asked_for_it() -> None:
    """"lance le titre par l'artiste" - and from the *resolved* track, which
    is the only version that describes what is about to play."""
    assert spotify.Track("spotify:track:x", "Starman", "David Bowie").spoken() == (
        "Starman par David Bowie"
    )


def test_a_track_is_named_in_english_too() -> None:
    """"By", not "par", when the request itself was in English - see
    round 34's language-matching fix."""
    assert spotify.Track("spotify:track:x", "Starman", "David Bowie").spoken("en") == (
        "Starman by David Bowie"
    )


def test_a_track_with_no_artist_is_not_named_par_nothing() -> None:
    assert spotify.Track("spotify:track:x", "Interlude", "").spoken() == "Interlude"


def test_missing_credentials_are_distinguished_from_a_failed_search() -> None:
    """Different things to say out loud: one is a setup step the user has not
    done, the other is a search that genuinely missed. Reporting the first as
    the second sends them looking for a better way to pronounce the title."""
    assert spotify.credentials_missing("", "") is True
    assert spotify.credentials_missing("id", "") is True
    assert spotify.credentials_missing("id", "secret") is False


def test_without_credentials_nothing_is_requested_at_all() -> None:
    """The common case until the user registers an app. It must not cost a
    network round trip, let alone a failed one, on every spoken request."""
    with patch("requests.get") as get:
        assert spotify.find_track("Alright", "", "") is None

    get.assert_not_called()


def test_a_search_failure_degrades_instead_of_raising() -> None:
    """This runs on the thread handling the turn. A network error there must
    become "j'ouvre la recherche", not an unhandled traceback."""
    with (
        patch("heypeer.executor.spotify._access_token", return_value="tok"),
        patch("requests.get", side_effect=OSError("network down")),
    ):
        assert spotify.find_track("Alright", "id", "secret") is None


def test_a_search_that_matches_nothing_is_not_a_track() -> None:
    with (
        patch("heypeer.executor.spotify._access_token", return_value="tok"),
        patch("requests.get", return_value=_api_response([])),
    ):
        assert spotify.find_track("asdfghjkl", "id", "secret") is None


def test_the_token_is_reused_rather_than_refetched_every_request() -> None:
    """A token lasts an hour. Fetching one per spoken request adds a round
    trip directly in front of the user, every time."""
    spotify._token = None
    token_response = MagicMock()
    token_response.json.return_value = {"access_token": "tok", "expires_in": 3600}
    token_response.raise_for_status.return_value = None

    with patch("requests.post", return_value=token_response) as post:
        spotify._access_token("id", "secret")
        spotify._access_token("id", "secret")

    assert post.call_count == 1
    spotify._token = None


def test_the_search_fallback_is_a_valid_quoted_uri() -> None:
    assert spotify.search_uri("Alright Kendrick Lamar") == (
        "spotify:search:Alright%20Kendrick%20Lamar"
    )
    assert " " not in spotify.search_uri("Petite Fleur & Co")


def test_launching_spotify_also_starts_the_music() -> None:
    """"Lance Spotify" means start it *and* play. Opening the app alone
    leaves the user in silence looking at a player that has not begun.

    The wait between the two is the point: pressing play before there is a
    player to press it on does nothing.
    """
    order: list = []
    with (
        patch("heypeer.executor.apps.launch", side_effect=lambda app: order.append(f"launch:{app.name}")),
        patch("heypeer.executor.spotify.press_play", side_effect=lambda: order.append("play")),
        patch("time.sleep", side_effect=lambda s: order.append(f"wait:{s}")),
    ):
        spotify.launch_and_play(settle_seconds=2.5)

    assert order == ["launch:Spotify", "wait:2.5", "play"]


def test_press_play_is_a_no_op_off_windows() -> None:
    """The media key is a Windows call. A dev box has nothing to press play
    on, and that is not an error."""
    with patch("sys.platform", "linux"):
        spotify.press_play()  # must not raise


# --- play_track -------------------------------------------------------------
#
# Found live: "lance un titre" would land on the track but not always start
# playing it. Reproduced as a cold-start-only gap: an already-running
# Spotify plays a track URI unaided, a cold-started one comes up paused - the
# same distinction launch_and_play already exists to handle for "lance
# Spotify" itself, one level down.


def test_an_already_running_spotify_is_left_alone() -> None:
    """The important direction: pressing play here would TOGGLE an
    already-playing track OFF. Correctness, not just a wasted step."""
    order: list = []
    with (
        patch("heypeer.executor.apps.is_running", return_value=True),
        patch("heypeer.executor.spotify.play_uri", side_effect=lambda u: order.append(f"open:{u}")),
        patch("heypeer.executor.spotify.press_play", side_effect=lambda: order.append("play")),
        patch("time.sleep", side_effect=lambda s: order.append(f"wait:{s}")),
    ):
        spotify.play_track("spotify:track:abc")

    assert order == ["open:spotify:track:abc"]


def test_a_cold_started_spotify_gets_a_settle_then_a_press() -> None:
    """The actual fix: mirrors launch_and_play's settle-then-press, applied
    to a track URI instead of the bare app."""
    order: list = []
    with (
        patch("heypeer.executor.apps.is_running", return_value=False),
        patch("heypeer.executor.spotify.play_uri", side_effect=lambda u: order.append(f"open:{u}")),
        patch("heypeer.executor.spotify.press_play", side_effect=lambda: order.append("play")),
        patch("time.sleep", side_effect=lambda s: order.append(f"wait:{s}")),
    ):
        spotify.play_track("spotify:track:abc", settle_seconds=2.5)

    assert order == ["open:spotify:track:abc", "wait:2.5", "play"]


def test_play_track_checks_for_spotify_specifically() -> None:
    """Checking any process named "Spotify.exe" and nothing else - the
    wrong process name would silently disable the whole fix."""
    with (
        patch("heypeer.executor.apps.is_running", return_value=True) as is_running,
        patch("heypeer.executor.spotify.play_uri"),
    ):
        spotify.play_track("spotify:track:abc")

    is_running.assert_called_once_with("Spotify.exe")


def test_the_search_fallback_never_presses_play() -> None:
    """play_uri (used for the two search-fallback branches in main.py) must
    stay a pure "open this" - there is nothing to press play on for a page of
    search results, and doing so would be a no-op at best and a stray pause
    at worst if something else happened to be playing."""
    with (
        patch("heypeer.executor.apps._open_target") as open_target,
        patch("heypeer.executor.spotify.press_play") as press_play,
    ):
        spotify.play_uri(spotify.search_uri("Starman"))

    open_target.assert_called_once()
    press_play.assert_not_called()
