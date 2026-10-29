"""Making a playlist in the Spotify desktop app, as fixed steps over CDP.

The demo's playlist used to be Hermes's job in the web player, and it was
the one part that failed rehearsals: renaming the new playlist took it up to
ten minutes (React ignores a value set from script), and its searches piled
up in the search box - "Weightless Marconi UnionTeardrop Massive Attack...".
Nothing about this task needs judgement, so it is a sequence instead: about
fifteen seconds, the same every time.

The desktop app is Chromium underneath and serves the same DevTools protocol
as Chrome when started with --remote-debugging-port - including the Microsoft
Store build, through its WindowsApps alias. `ensure_running` restarts it that
way when it is running without the port.

Selectors are the app's data-testid attributes where it has them, and menu
and button labels in both English and French otherwise, since which one
shows depends on the account's language.
"""

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

DEFAULT_PORT = 9223

APP_PATHS = (
    r"%APPDATA%\Spotify\Spotify.exe",
    # The Microsoft Store build: the alias is the only path it can be
    # started from with arguments.
    r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe",
)

START_TIMEOUT_SECONDS = 25.0

ROWS = '[role="row"]'
SEARCH = ('document.querySelector(\'input[role="searchbox"][placeholder*="songs"], '
          'input[role="searchbox"][placeholder*="titres"]\')')
RESULTS = '[data-testid="playlist-inline-curation-results"] [role="row"]'
ADD = '[data-testid="add-to-playlist-button"]'
TRACK_ROWS = '[data-testid="playlist-tracklist"] [data-testid="tracklist-row"]'


def port() -> int:
    try:
        return int(os.environ.get("HEYPEER_SPOTIFY_DEBUG_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def is_debuggable() -> bool:
    try:
        with urllib.request.urlopen(  # noqa: S310 - localhost only
            f"http://127.0.0.1:{port()}/json/version", timeout=1.5
        ):
            return True
    except Exception:
        return False


def _app() -> "Path | None":
    for raw in APP_PATHS:
        path = Path(os.path.expandvars(raw))
        if path.exists():
            return path
    return None


def ensure_running() -> bool:
    """Starts the app with its debugging port, restarting it if it is open
    without one, and returns whether the port answers."""
    if is_debuggable():
        return True
    app = _app()
    if app is None:
        return False
    subprocess.run(["taskkill", "/IM", "Spotify.exe", "/F"],  # noqa: S603, S607
                   capture_output=True)
    time.sleep(1.5)
    subprocess.Popen([str(app), f"--remote-debugging-port={port()}"])  # noqa: S603
    deadline = time.time() + START_TIMEOUT_SECONDS
    while time.time() < deadline:
        if is_debuggable():
            # The port opens before the interface has drawn.
            time.sleep(4)
            return True
        time.sleep(0.5)
    return False


def bring_to_front(stage: "tuple[int, int, int, int] | None" = None) -> bool:
    """Raises the app's window, onto `stage` when given. Found by process,
    not title: the title is whatever track is playing."""
    try:
        out = subprocess.run(  # noqa: S603, S607
            ["tasklist", "/FI", "IMAGENAME eq Spotify.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True).stdout
        pids = {int(line.split('","')[1]) for line in out.splitlines() if '","' in line}
        import uiautomation as auto

        windows = [w for w in auto.GetRootControl().GetChildren()
                   if w.ProcessId in pids and w.ClassName == "Chrome_WidgetWin_1" and w.Name]
        if not windows:
            return False
        from heypeer.executor.foreground import raise_window

        raise_window(windows[0].NativeWindowHandle, stage=stage)
        return True
    except Exception:
        return False


def _playlist_rows_js(name: str) -> str:
    """Library rows for playlists called `name`."""
    return (f"[...document.querySelectorAll('{ROWS}')].filter(r => "
            f"r.querySelector('[aria-labelledby*=\"spotify:playlist:\"]') && "
            f"r.innerText.split('\\n')[0].trim() === {json.dumps(name)})")


def _menu_item_js(*labels: str) -> str:
    wanted = json.dumps([label.lower() for label in labels])
    return ("[...document.querySelectorAll('[role=\"menuitem\"], [role=\"menu\"] button')]"
            f".filter(e => e.offsetParent).find(e => {wanted}.includes("
            "e.innerText.trim().split('\\n')[0].trim().toLowerCase()))")


def delete_playlists(page, name: str, log=print) -> int:
    """Deletes every playlist in the library called `name`, through its
    right-click menu, and returns how many went."""
    deleted = 0
    for _ in range(5):
        if not page.js(f"{_playlist_rows_js(name)}.length"):
            break
        page.click(f"{_playlist_rows_js(name)}[0]", button="right")
        page.wait_for(f"!!({_menu_item_js('Delete', 'Supprimer')})", timeout=5)
        page.click(_menu_item_js("Delete", "Supprimer"))
        confirm = ("[...document.querySelectorAll('[role=\"dialog\"] button, "
                   "[role=\"alertdialog\"] button')].filter(b => b.offsetParent)"
                   ".find(b => ['delete', 'supprimer'].includes(b.innerText.trim().toLowerCase()))")
        page.wait_for(f"!!({confirm})", timeout=5)
        page.click(confirm)
        time.sleep(1.5)
        deleted += 1
        log(f"Spotify: deleted an old {name!r} playlist.")
    return deleted


def create_playlist(page, name: str, log=print) -> str:
    """Creates an empty playlist called `name` and returns its id."""
    before = set(page.js("[...document.querySelectorAll('[aria-labelledby*=\"spotify:playlist:\"]')]"
                         ".map(e => e.getAttribute('aria-labelledby').match(/spotify:playlist:(\\w+)/)[1])"))
    create = ("[...document.querySelectorAll('button')].find(b => "
              "['create', 'créer'].includes((b.getAttribute('aria-label') || '').toLowerCase()))")
    page.click(create)
    playlist_item = ("[...document.querySelectorAll('[role=\"menuitem\"], [role=\"menu\"] button, "
                     "[role=\"dialog\"] button')].filter(e => e.offsetParent)"
                     ".find(e => /^playlist\\b/i.test(e.innerText.trim()))")
    page.wait_for(f"!!({playlist_item})", timeout=5)
    page.click(playlist_item)
    title = "document.querySelector('[data-testid=\"entityTitle\"]')"
    page.wait_for(f"!!{title}", timeout=10)
    time.sleep(1)
    page.click(title)
    name_input = "document.querySelector('[data-testid=\"playlist-edit-details-name-input\"]')"
    page.wait_for(f"!!{name_input}", timeout=5)
    page.click(name_input)
    page.select_all_and_delete()
    page.type_text(name)
    page.click("document.querySelector('[data-testid=\"playlist-edit-details-save-button\"]')")
    page.wait_for(f"{title} && {title}.innerText.trim() === {json.dumps(name)}", timeout=8)
    new_id = page.wait_for(
        "(() => { const ids = [...document.querySelectorAll('[aria-labelledby*=\"spotify:playlist:\"]')]"
        ".map(e => e.getAttribute('aria-labelledby').match(/spotify:playlist:(\\w+)/)[1]);"
        f" return ids.find(i => !{json.dumps(sorted(before))}.includes(i)) || null; }})()",
        timeout=8)
    log(f"Spotify: created playlist {name!r} ({new_id}).")
    return new_id


def add_track(page, title: str, artist: str, log=print) -> bool:
    """Searches the playlist's own search box for one track and adds the
    first song whose title and artist match - songs only: the add button
    is on episodes too, and a podcast once slipped into the playlist."""
    page.click(SEARCH)
    # Emptied every time: typed into as it was, the box kept each search
    # and ran them together.
    page.select_all_and_delete()
    page.type_text(f"{title} {artist}")
    row = (f"[...document.querySelectorAll('{RESULTS}')].find(r => r.querySelector('{ADD}') && "
           f"r.innerText.toLowerCase().startsWith({json.dumps(title.lower())}) && "
           f"r.innerText.toLowerCase().includes({json.dumps(artist.lower())}) && "
           "!/episode|épisode/i.test(r.innerText))")
    try:
        page.wait_for(f"!!({row})", timeout=8)
    except Exception:
        log(f"Spotify: no match for {title} - {artist}.")
        return False
    count = page.js(f"document.querySelectorAll('{TRACK_ROWS}').length")
    page.click(f"({row}).querySelector('{ADD}')")
    try:
        page.wait_for(f"document.querySelectorAll('{TRACK_ROWS}').length > {count}", timeout=6)
    except Exception:
        log(f"Spotify: {title} did not appear in the playlist.")
        return False
    log(f"Spotify: added {title} - {artist}.")
    return True


def tracks(page) -> "list[str]":
    return page.js(f"[...document.querySelectorAll('{TRACK_ROWS}')]"
                   ".map(r => r.innerText.split('\\n').slice(1, 3).join(' - '))")


def make_playlist(name: str, songs: "list[tuple[str, str]]", count: int = 5,
                  log=print) -> "tuple[str, list[str]]":
    """Replaces any playlist called `name` with a new one holding the first
    `count` of `songs` that are found, and returns its share link and its
    tracks."""
    from heypeer.executor.cdp import Page

    page = Page(port(), "xpui")
    try:
        delete_playlists(page, name, log)
        playlist_id = create_playlist(page, name, log)
        added = 0
        for title, artist in songs:
            if added >= count:
                break
            if add_track(page, title, artist, log):
                added += 1
                # A beat between tracks, so the audience sees each one land.
                time.sleep(0.6)
        return f"https://open.spotify.com/playlist/{playlist_id}", tracks(page)
    finally:
        page.close()
