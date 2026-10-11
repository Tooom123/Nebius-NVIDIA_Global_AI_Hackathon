"""Launching desktop applications by name.

The first capability Hey Peer has that is not about files, and deliberately
built as a *registry* rather than "run whatever the model said". Nemotron
resolves a spoken phrase to an app name and this module decides whether that
name is something it knows how to start - because the failure mode of the
obvious alternative is handing a language model's output to the shell.

Launching tries, in order, every route an app might actually have:

1. A **URI scheme** (`spotify:`) when the app registers one *and it is
   trustworthy* - genuinely documented, not just plausible-looking. Spotify
   and Steam both really do register one system-wide; this is the right
   answer where it holds, since the OS resolves it to whatever the user has
   installed (Store app, desktop build, either version) the same way a link
   in a browser does. A scheme that turns out not to be registered just
   fails fast and costs nothing - the next route is tried regardless.
2. A **Start Menu shortcut** matching the app's name or an alias. This is
   how a person actually opens most installed software, and it is why it
   comes before a bare executable name: Discord, Slack, Teams, and most
   other Electron/Squirrel-installed apps install to a per-user, versioned
   folder under `%LOCALAPPDATA%` that is never on PATH, and their real
   launcher (`Update.exe` for Squirrel apps specifically) needs a
   command-line argument to start the app rather than open its own updater
   - `os.startfile` cannot pass one. Every installer, Squirrel included,
   drops a shortcut in the Start Menu as a side effect of installing
   *specifically* so the shell can find the app without any of that - the
   shortcut already encodes the correct target, arguments and working
   directory.
3. An **executable name**, resolved to a real path first via `shutil.which`
   (PATH) or a known install location, rather than handed to `os.startfile`
   as a bare string - `os.startfile` wraps `ShellExecute`, which is not
   documented to search PATH for an extensionless name the way
   `subprocess`/`CreateProcess` is, so a bare `"discord"` attempt is not
   reliable even when an executable really is on PATH.

Unknown names are refused rather than guessed at. "Lance Machin" gets an
answer saying Hey Peer doesn't know that app, which is a worse experience for
exactly one turn and is not a way to start arbitrary processes.

None of this has been run against a real Windows install - every mechanism
above is reasoned from how Windows installers and `ShellExecute` are
documented to behave, not observed. See `_find_start_menu_shortcut` and
`launch` for what is and isn't independently testable from here.
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
    # These five are Electron/Squirrel-style installs: no reliable PATH
    # entry, and their URI scheme (if any) is a guess, not a documented,
    # verified one the way Spotify's and Steam's are - the Start Menu
    # shortcut search is what actually launches them in practice; the
    # scheme is kept as a free first attempt only.
    App(name="Discord", aliases=("discorde",), uri_scheme="discord:", executable="discord"),
    App(name="Slack", aliases=(), uri_scheme="slack:", executable="slack"),
    App(name="Teams", aliases=("microsoft teams",), uri_scheme="msteams:", executable="teams"),
    App(name="Zoom", aliases=(), uri_scheme="zoommtg:", executable="zoom"),
    App(name="WhatsApp", aliases=("ouatsape",), uri_scheme="whatsapp:", executable="whatsapp"),
    App(name="Telegram", aliases=("telegram desktop",), uri_scheme="tg:", executable="telegram"),
    App(name="Steam", aliases=(), uri_scheme="steam:", executable="steam"),
    App(name="VLC", aliases=("vlc media player", "le lecteur video"), executable="vlc"),
    App(name="Word", aliases=("microsoft word",), executable="winword"),
    App(name="Excel", aliases=("microsoft excel",), executable="excel"),
    App(name="PowerPoint", aliases=("power point", "microsoft powerpoint"), executable="powerpnt"),
    App(name="Outlook", aliases=("les mails", "ma boite mail"), executable="outlook"),
    App(name="Explorateur", aliases=("explorateur de fichiers", "explorer", "les fichiers"),
        executable="explorer"),
    App(name="Bloc-notes", aliases=("notepad", "le bloc note"), executable="notepad"),
    App(name="Calculatrice", aliases=("calculette", "calc"), executable="calc"),
    App(name="Parametres", aliases=("les parametres", "reglages"), uri_scheme="ms-settings:"),
    App(name="Terminal", aliases=("invite de commandes", "cmd", "console"), executable="wt"),
    App(name="VS Code", aliases=("visual studio code", "vscode", "code"), executable="code"),
    App(name="CapCut", aliases=("cap cut", "capcute"), executable="capcut",
        windows_paths=(r"%LOCALAPPDATA%\CapCut\Apps\CapCut.exe",)),
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


# Both scopes a Windows installer can put a shortcut in: the per-user Start
# Menu (where Squirrel/Electron apps like Discord install theirs) and the
# all-users one (traditional MSI installers).
_START_MENU_ROOTS = (
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs",
    r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs",
)


def _find_start_menu_shortcut(app: App, roots: "tuple[str, ...] | None" = None) -> "Path | None":
    """A `.lnk` file under the Start Menu matching `app`'s name or an alias,
    searched recursively (installers commonly nest shortcuts in a publisher
    or suite subfolder - "Discord.lnk" sits directly under Programs, but
    "Microsoft Office Tools/Word.lnk" does not).

    Exact match (case-insensitive) against the shortcut's filename first;
    a substring match either way second, since a shortcut's real name
    sometimes only partially overlaps what is in `KNOWN_APPS` ("VLC media
    player.lnk" for `App(name="VLC", aliases=("vlc media player", ...))` is
    an exact-alias match, but an install this code has not specifically
    special-cased might only ever match this loosely).

    `roots` is overridable so this is independently testable without a real
    Windows Start Menu - see `tests/test_apps.py`.
    """
    import glob
    from pathlib import Path

    wanted = [_normalise(key) for key in (app.name, *app.aliases)]
    search_roots = roots if roots is not None else _START_MENU_ROOTS

    found: "list[Path]" = []
    for root in search_roots:
        expanded = os.path.expandvars(root) if roots is None else root
        if not os.path.isdir(expanded):
            continue
        found.extend(
            Path(p) for p in glob.glob(os.path.join(expanded, "**", "*.lnk"), recursive=True)
        )

    for shortcut in found:
        if _normalise(shortcut.stem) in wanted:
            return shortcut
    for shortcut in found:
        stem = _normalise(shortcut.stem)
        if any(w in stem or stem in w for w in wanted):
            return shortcut
    return None


def launch(app: App) -> None:
    """Starts `app`: its URI scheme first (a free attempt, tried even where
    it is only a guess - see `KNOWN_APPS`), then a matching Start Menu
    shortcut, then a resolved executable path.

    Raises `LaunchFailed` if nothing works, which the caller turns into a
    spoken message - an app the user does not actually have installed is a
    normal thing to be asked for, not an error worth a traceback. Failing
    honestly here matters more than usual: the previous version of this
    function could "succeed" at opening the wrong thing (a Squirrel
    updater window instead of the app it updates) and report it as done.
    """
    attempts = []
    if app.uri_scheme:
        attempts.append(app.uri_scheme)
    if sys.platform == "win32":
        shortcut = _find_start_menu_shortcut(app)
        if shortcut is not None:
            attempts.append(str(shortcut))
    attempts.extend(_executable_candidates(app))

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


def is_running(process_name: str) -> bool:
    """Whether a process named `process_name` (e.g. "Spotify.exe") is
    currently running.

    Windows-only, and False everywhere else - the only caller so far
    (`spotify.play_track`) only needs the distinction on Windows, and a
    wrong "not running" answer there just costs one harmless extra
    settle-and-press, never a missing one.

    Uses `tasklist` rather than a process-listing dependency: this project
    has stayed deliberately light on dependencies (Piper over a heavier TTS
    engine, no `psutil`), and `tasklist` is a standard part of Windows with
    nothing to install.
    """
    if sys.platform != "win32":
        return False
    try:
        output = subprocess.check_output(  # noqa: S603, S607
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/NH"],
            text=True,
            # Explicit, because Python defaults to the console's
            # locale encoding - cp1252 on a French Windows - and
            # that raises UnicodeDecodeError on any byte above
            # 0x7f. Seen for real: a subprocess reader thread died
            # on 0x8f mid-output, losing the rest of the result.
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return process_name.lower() in output.lower()
