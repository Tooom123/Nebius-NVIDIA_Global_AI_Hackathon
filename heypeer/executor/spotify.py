"""Playing something specific on Spotify.

Two different requests, two different mechanisms:

* **"lance Spotify"** - open the app and press play. Starting Spotify does
  not start music, so the media play/pause key is sent once it is up. That
  key is a system-wide command the OS routes to whatever is playing, which is
  why it works without Spotify granting anything: the same key on a keyboard
  does the same thing.
* **"lance X par Y sur Spotify"** - resolve the track first, then open its
  URI. `spotify:track:<id>` handed to the desktop app plays that track
  directly, so all that is needed is the id.

## Why the search needs credentials, and why they are only a client id

Resolving "Alright par Kendrick Lamar" to a track id is a Web API search.
That endpoint takes an **application** token - the client-credentials flow -
not a user one: no login prompt, no OAuth redirect, no Premium account, no
access to anything belonging to the user. The credentials come from a free
app registered at developer.spotify.com and go in `.env` as
`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.

Without them Hey Peer falls back to `spotify:search:<query>`, which opens the
search results in the app. That is a real degradation - it does not play
anything - so `search_track` reports which of the two happened and the caller
says so out loud rather than claiming to have started the music.

Playback itself is deliberately *not* the Web API's `/me/player/play`: that
one does need a user OAuth flow and a Premium subscription. Opening a URI
needs neither and drives the app the user already has open.
"""

import time
import urllib.parse
from dataclasses import dataclass

SEARCH_URL = "https://api.spotify.com/v1/search"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# How long to give Spotify to come up before sending play. Long enough for a
# cold start on a normal machine; the key is harmless if it arrives early,
# it just does nothing.
LAUNCH_SETTLE_SECONDS = 2.5

_token: "tuple[str, float] | None" = None  # (token, expiry timestamp)


class SpotifyUnavailable(RuntimeError):
    """Spotify could not be searched or driven."""


@dataclass(frozen=True)
class Track:
    """One resolved track: what to play, and what to say about it."""

    uri: str
    title: str
    artist: str

    def spoken(self, language: str = "fr") -> str:
        """"Starman par David Bowie" (or "Starman by David Bowie") - the
        phrasing the user asked for, in whichever language they asked in.
        Said from the *resolved* track rather than from what they said or
        what the model wrote, because that is the only version that
        reflects what is actually about to play."""
        if not self.artist:
            return self.title
        preposition = "by" if language == "en" else "par"
        return f"{self.title} {preposition} {self.artist}"


def credentials_missing(client_id: str, client_secret: str) -> bool:
    """Whether searching is possible at all.

    Worth its own function because "no credentials" and "found nothing" are
    different things to say out loud: one is a setup step the user has not
    done, the other is a search that genuinely missed. Reporting the first as
    the second sends them looking for a better way to pronounce the title.
    """
    return not (client_id and client_secret)


def _access_token(client_id: str, client_secret: str) -> str:
    """An application token, cached until shortly before it expires.

    Cached because a token lasts an hour and every spoken request would
    otherwise pay a round trip to get one - directly in front of the user,
    who is waiting for music."""
    global _token
    if _token is not None and _token[1] > time.time():
        return _token[0]

    import requests

    response = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload["access_token"]
    # A minute of slack, so a token cannot expire between the check and the
    # request that uses it.
    _token = (token, time.time() + int(payload.get("expires_in", 3600)) - 60)
    return token


def _first_track(query: str, client_id: str, client_secret: str) -> "dict | None":
    """The best match for `query`, as the API returns it, or None.

    None covers every way this can fail to produce a track - no credentials,
    nothing found, network or auth error - because they all lead to the same
    place: fall back to opening the search and say so. A search failure must
    degrade, never raise, since this runs on the thread handling the turn.
    """
    if not query or not client_id or not client_secret:
        return None

    import requests

    try:
        response = requests.get(
            SEARCH_URL,
            params={"q": query, "type": "track", "limit": 1, "market": "FR"},
            headers={"Authorization": f"Bearer {_access_token(client_id, client_secret)}"},
            timeout=10,
        )
        response.raise_for_status()
        items = response.json().get("tracks", {}).get("items", [])
    except Exception:
        return None
    return items[0] if items else None


def find_track(query: str, client_id: str = "", client_secret: str = "") -> "Track | None":
    """The `Track` best matching `query`, or None.

    The URI and the title/artist come from one search on purpose: the first is
    what gets played and the second is what gets said, and asking twice would
    double the wait in front of someone who just asked for music. Saying what
    was actually found is also how the user discovers the search matched
    something other than what they said.
    """
    item = _first_track(query, client_id, client_secret)
    if item is None:
        return None
    return Track(
        uri=item["uri"],
        title=item["name"],
        artist=", ".join(a["name"] for a in item.get("artists", [])),
    )


def search_uri(query: str) -> str:
    """`spotify:search:...`, which opens the search results in the app.

    The fallback when a track cannot be resolved. It shows the user what they
    asked for; it does not play it.
    """
    return "spotify:search:" + urllib.parse.quote(query)


def play_uri(uri: str) -> None:
    """Opens a `spotify:` URI in the desktop app - and nothing more.

    This alone is the right call for a search-results URI, where there is
    nothing to press play on. For a track, use `play_track` instead: whether
    playback actually starts depends on whether Spotify was already running,
    which this function does not know or care about.
    """
    from heypeer.executor.apps import _open_target

    _open_target(uri)


def play_track(uri: str, settle_seconds: float = LAUNCH_SETTLE_SECONDS) -> None:
    """Plays a `spotify:track:` URI - reliably, unlike calling `play_uri` on
    one directly.

    Found live: "lance un titre" would land on the track but not always
    start playing it. The cause is the same cold-start gap `launch_and_play`
    already exists to close, one level down: opening a track URI in an
    *already-running* Spotify plays it immediately, exactly like clicking a
    spotify: link while the app is open. Opening one while Spotify is closed
    cold-starts the app, which comes up showing the track - paused, the same
    way plain "lance Spotify" does not start music on its own.

    So the fix only fires on a cold start, checked with `apps.is_running`
    before opening anything: an already-running Spotify is left alone, since
    it already plays the track unaided, and pressing play on it would toggle
    an already-playing track *off*.
    """
    from heypeer.executor.apps import is_running

    was_running = is_running("Spotify.exe")
    play_uri(uri)
    if not was_running:
        time.sleep(settle_seconds)
        press_play()


def press_play() -> None:
    """Sends the system media play/pause key.

    Windows-only, and a no-op elsewhere rather than an error: this is the
    "and start the music" half of "lance Spotify", and a dev box with no
    Spotify has nothing to press play on.
    """
    import sys

    if sys.platform != "win32":
        return
    import ctypes

    vk_media_play_pause = 0xB3
    keyeventf_keyup = 0x0002
    user32 = ctypes.windll.user32
    user32.keybd_event(vk_media_play_pause, 0, 0, 0)
    user32.keybd_event(vk_media_play_pause, 0, keyeventf_keyup, 0)


def launch_and_play(settle_seconds: float = LAUNCH_SETTLE_SECONDS) -> None:
    """Opens Spotify and starts playback - "lance Spotify" in full.

    The wait is why this is not two calls at the call site: pressing play
    before the app has a player to press it on does nothing, and the user
    hears silence and assumes it failed."""
    from heypeer.executor.apps import KNOWN_APPS, launch

    launch(next(app for app in KNOWN_APPS if app.name == "Spotify"))
    time.sleep(settle_seconds)
    press_play()
