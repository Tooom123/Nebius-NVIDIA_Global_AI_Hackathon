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
    App(name="Chrome", aliases=("google chrome", "le navigateur"), executable="chrome"),
    App(name="Firefox", aliases=(), executable="firefox"),
    App(name="Discord", aliases=(), executable="discord"),
    App(name="Steam", aliases=(), uri_scheme="steam:", executable="steam"),
    App(name="Explorateur", aliases=("explorateur de fichiers", "explorer", "les fichiers"),
        executable="explorer"),
    App(name="Bloc-notes", aliases=("notepad", "le bloc note"), executable="notepad"),
    App(name="Calculatrice", aliases=("calculette", "calc"), executable="calc"),
    App(name="Terminal", aliases=("invite de commandes", "cmd", "console"), executable="wt"),
    App(name="VS Code", aliases=("visual studio code", "vscode", "code"), executable="code"),
)


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
