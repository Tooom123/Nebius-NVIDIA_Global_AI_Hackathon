"""Launching desktop applications by name.

The first capability Hey Peer has that is not about files, and deliberately
built as a *registry* rather than "run whatever the model said". Nemotron
resolves a spoken phrase to an app name and this module decides whether that
name is something it knows how to start - because the failure mode of the
obvious alternative is handing a language model's output to the shell.

Launching goes through the most specific route each app actually has:

1. A **URI scheme** (`spotify:`) when the app registers one. This is the
   right answer where it exists: the OS resolves it to whatever the user has
   installed - Store app, desktop build, either version - and it is the same
   mechanism a link in a browser uses.
2. An **executable name** otherwise, resolved through PATH and, on Windows,
   the App Paths registry that `os.startfile` consults.

Unknown names are refused rather than guessed at. "Lance Machin" gets an
answer saying Hey Peer doesn't know that app, which is a worse experience for
exactly one turn and is not a way to start arbitrary processes.
"""

import difflib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field


class LaunchFailed(RuntimeError):
    """The app is known but could not be started."""


@dataclass(frozen=True)
class App:
    """One launchable application.

    `uri_scheme` is preferred over `executable` when both are set - see the
    module docstring. `aliases` are the other things people say for it;
    matching is case- and accent-insensitive on the caller's side.
    """

    name: str  # how Hey Peer says it back
    aliases: tuple = ()
    uri_scheme: "str | None" = None
    executable: "str | None" = None
    # Windows-only fallbacks, tried in order, for apps that register neither a
    # URI scheme nor an App Paths entry.
    windows_paths: tuple = field(default_factory=tuple)


KNOWN_APPS = (
    App(
        name="Spotify",
        aliases=("spoti", "spotifaï", "la musique", "musique"),
        uri_scheme="spotify:",
        executable="spotify",
        windows_paths=(r"%APPDATA%\Spotify\Spotify.exe",),
    ),
    App(name="Chrome", aliases=("google chrome", "le navigateur", "navigateur"),
        executable="chrome",
        windows_paths=(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
                       r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
                       r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")),
    App(name="Firefox", aliases=(), executable="firefox"),
    App(name="Edge", aliases=("microsoft edge",), executable="msedge"),
    App(name="Discord", aliases=("discorde",), uri_scheme="discord:", executable="discord",
        windows_paths=(r"%LOCALAPPDATA%\Discord\Update.exe",)),
    App(name="Slack", aliases=(), uri_scheme="slack:", executable="slack"),
    App(name="Teams", aliases=("microsoft teams",), uri_scheme="msteams:", executable="teams"),
    App(name="Zoom", aliases=(), uri_scheme="zoommtg:", executable="zoom"),
    App(name="WhatsApp", aliases=("ouatsape",), uri_scheme="whatsapp:", executable="whatsapp"),
    App(name="Telegram", aliases=(), uri_scheme="tg:", executable="telegram"),
    App(name="Steam", aliases=(), uri_scheme="steam:", executable="steam"),
    App(name="VLC", aliases=("vlc media player", "le lecteur video"), executable="vlc"),
    App(name="Word", aliases=("microsoft word",), executable="winword"),
    App(name="Excel", aliases=("microsoft excel",), executable="excel"),
    App(name="PowerPoint", aliases=("power point",), executable="powerpnt"),
    App(name="Outlook", aliases=("les mails", "ma boite mail"), executable="outlook"),
    App(name="Explorateur", aliases=("explorateur de fichiers", "explorer", "les fichiers"),
        executable="explorer"),
    App(name="Bloc-notes", aliases=("notepad", "le bloc note"), executable="notepad"),
    App(name="Calculatrice", aliases=("calculette", "calc"), executable="calc"),
    App(name="Parametres", aliases=("les parametres", "reglages"), uri_scheme="ms-settings:"),
    App(name="Terminal", aliases=("invite de commandes", "cmd", "console"), executable="wt"),
    App(name="VS Code", aliases=("visual studio code", "vscode", "code"), executable="code"),
)

# Where "cherche X sur internet" goes. A plain query string appended to a
# search engine, not a URL the model composed - same reasoning as the app
# registry: nothing here opens an address chosen by a language model.
SEARCH_ENGINE_URL = "https://www.google.com/search?q={query}"

# Which app to try opening web results in. Falling back to the default
# browser is not a failure - it is what the user configured.
DEFAULT_BROWSER = "Chrome"


def _normalise(text: str) -> str:
    """Lowercases and strips accents, so "spotifaï" and "Spotify" compare
    equal. The spoken name arrives from a transcript and then through a model,
    and neither guarantees the accents or the case of anything."""
    import unicodedata

    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def resolve_app(spoken_name: str) -> "App | None":
    """The app `spoken_name` refers to, or None if it isn't one Hey Peer
    knows.

    Same shape as `runner.resolve_existing_filename`, and for the same reason:
    a spoken name arrives approximate. Exact match, then alias, then fuzzy -
    and declining beats guessing, since the answer here starts a process.
    """
    if not spoken_name:
        return None
    wanted = _normalise(spoken_name)
    if not wanted:
        return None

    by_key = {}
    for app in KNOWN_APPS:
        for key in (app.name, *app.aliases):
            by_key.setdefault(_normalise(key), app)

    if wanted in by_key:
        return by_key[wanted]

    close = difflib.get_close_matches(wanted, list(by_key), n=1, cutoff=0.8)
    return by_key[close[0]] if close else None


def _open_target(target: str) -> None:
    """Hands `target` - a URI or an executable name - to the OS to open.

    `os.startfile` is the Windows equivalent of double-clicking, which is what
    makes a URI scheme work at all; it does not exist on other platforms, so
    the dev sandbox takes the `xdg-open` path instead.
    """
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606 - a registry entry, not user input
        return
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener is None:
        raise LaunchFailed(f"No way to open {target!r} on this platform")
    subprocess.Popen(  # noqa: S603
        [opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def launch(app: App) -> None:
    """Starts `app`, trying its URI scheme first and its executable after.

    Raises `LaunchFailed` if nothing works, which the caller turns into a
    spoken message - an app the user does not actually have installed is a
    normal thing to be asked for, not an error worth a traceback.
    """
    attempts = []
    if app.uri_scheme:
        attempts.append(app.uri_scheme)
    if app.executable:
        attempts.append(app.executable)
    for path in app.windows_paths:
        if sys.platform == "win32":
            attempts.append(os.path.expandvars(path))

    last_error: "Exception | None" = None
    for target in attempts:
        try:
            _open_target(target)
            return
        except Exception as exc:
            last_error = exc
    raise LaunchFailed(f"Could not start {app.name}: {last_error}")


def search_url(query: str) -> str:
    """The search-results URL for `query`.

    The query is percent-encoded into a fixed template rather than the model
    being asked for a URL. A search string can say anything; a URL can *go*
    anywhere, and the difference matters when the text originated in a
    microphone.
    """
    import urllib.parse

    return SEARCH_ENGINE_URL.format(query=urllib.parse.quote_plus(query))


def open_url(url: str, prefer_app: "str | None" = DEFAULT_BROWSER) -> None:
    """Opens `url`, in `prefer_app` if that browser can be found.

    `os.startfile` takes no arguments, so opening a URL *in a named browser*
    means finding its executable and passing the URL to it. When that fails -
    which it usually does on Windows, where browsers live in the App Paths
    registry rather than on PATH - the URL goes to the default handler
    instead. That is the right outcome anyway: the default browser is the one
    the user chose.
    """
    if prefer_app:
        app = resolve_app(prefer_app)
        if app is not None:
            for candidate in _executable_candidates(app):
                try:
                    subprocess.Popen(  # noqa: S603
                        [candidate, url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except Exception:
                    continue
    _open_target(url)


def _executable_candidates(app: App) -> list:
    """Concrete paths that might be `app`'s executable, best first."""
    candidates = []
    if app.executable:
        found = shutil.which(app.executable)
        if found:
            candidates.append(found)
    if sys.platform == "win32":
        for path in app.windows_paths:
            expanded = os.path.expandvars(path)
            if os.path.isfile(expanded):
                candidates.append(expanded)
    return candidates
