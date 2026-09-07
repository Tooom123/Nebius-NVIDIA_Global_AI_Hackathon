"""Choosing the pointer's colour, once, on first run.

## Why this is the only onboarding step

Everything else Hey Peer needs is either discovered (the watched folder has
a default, the voices download themselves) or genuinely technical (an API
key, which belongs in `.env` and not in a dialog). The pointer's colour is
different: it is the one setting with no correct default, because it
depends on what the user's screen already looks like. Red on a dark editor
and red on a red-themed desktop are not the same choice.

So it is asked once, stored, and never asked again - `has_been_asked()` is
what the caller checks. A first run that opens a dialog is onboarding; a
second one that opens the same dialog is an annoyance.

## Why the choice is written to .env rather than a settings file

`HEYPEER_CURSOR_COLOR` is already how the running app reads it (see
`main.py`'s `_cursor_color_from_env`), and `.env` is already where this
project's configuration lives and is already gitignored. Adding a second
configuration mechanism for one value would mean two places to look when it
is wrong.

## Threading

Tk must not be created from inside a tray menu callback - see
`tray/prompt.py`'s module docstring for the symptoms, which were observed
for real on Windows. `ask_cursor_color` has the same constraint and the
same remedy: call it from its own thread.
"""

from pathlib import Path

from heypeer.tray.cursor_render import DEFAULT_COLOR

ENV_KEY = "HEYPEER_CURSOR_COLOR"

# Offered alongside the free picker: colours that stay legible against the
# things a pointer actually sits on. Red first, since that is the default
# and the user chose it.
PRESETS = (
    ("Rouge", (255, 0, 0)),
    ("Cyan", (34, 211, 238)),
    ("Vert", (34, 197, 94)),
    ("Violet", (168, 85, 247)),
    ("Orange", (249, 115, 22)),
    ("Blanc", (245, 245, 245)),
)


def env_path() -> Path:
    """Where the choice is written. The project's own `.env`, beside the
    API key it already holds."""
    return Path(__file__).resolve().parent.parent.parent / ".env"


def has_been_asked(path: "Path | None" = None) -> bool:
    """Whether a colour has already been chosen.

    Reads the file rather than the environment: the environment reflects
    what was loaded at startup, and this has to be true immediately after
    writing, before any restart.
    """
    path = path or env_path()
    if not path.is_file():
        return False
    try:
        return any(
            line.strip().startswith(f"{ENV_KEY}=")
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return False


def save_color(rgb: "tuple[int, int, int]", path: "Path | None" = None) -> bool:
    """Writes the choice to `.env`, replacing any existing value.

    Returns whether it worked. A failure here is not fatal - the pointer
    keeps the default and the user can set the variable by hand - so the
    caller logs rather than stopping.
    """
    path = path or env_path()
    line = f"{ENV_KEY}={rgb[0]},{rgb[1]},{rgb[2]}"
    try:
        existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        kept = [ln for ln in existing if not ln.strip().startswith(f"{ENV_KEY}=")]
        # A trailing blank line in the source would otherwise push the new
        # setting away from the rest and accumulate one gap per rewrite.
        while kept and not kept[-1].strip():
            kept.pop()
        path.write_text("\n".join(kept + [line]) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def parse_color(text: str) -> "tuple[int, int, int] | None":
    """A colour from what a person typed: "#ff0000", "ff0000", or
    "255,0,0". None if it is not one of those.

    Accepting three spellings because the dialog offers a hex picker and
    the env var is decimal, and a user who copies one into the other should
    not be told they are wrong.
    """
    text = text.strip()
    if not text:
        return None
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 6:
        try:
            return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 3:
        try:
            return tuple(max(0, min(255, int(p))) for p in parts)
        except ValueError:
            return None
    return None


def ask_cursor_color() -> "tuple[int, int, int] | None":
    """Opens the colour picker and returns the chosen colour, or None if
    the user cancelled.

    Must be called from its own thread - see this module's docstring.
    """
    import tkinter as tk
    from tkinter import colorchooser

    root = tk.Tk()
    root.withdraw()
    try:
        chosen = colorchooser.askcolor(
            color="#%02x%02x%02x" % DEFAULT_COLOR,
            title="Hey Peer - couleur du curseur",
        )
    except Exception:
        return None
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    if not chosen or chosen[0] is None:
        return None
    return tuple(int(c) for c in chosen[0])


def run_if_needed(log=print) -> "tuple[int, int, int]":
    """The whole first-run step: ask if it has not been asked, save the
    answer, and return the colour to use either way.

    Returns the default on every failure path - cancelled, no display, an
    unwritable `.env` - so a caller can use the result unconditionally.
    """
    if has_been_asked():
        return DEFAULT_COLOR

    try:
        chosen = ask_cursor_color()
    except Exception as exc:
        log(f"[onboarding] Colour picker unavailable: {exc}")
        return DEFAULT_COLOR

    if chosen is None:
        # Cancelling is a valid answer meaning "the default is fine", and
        # it is recorded so the dialog does not come back next launch.
        save_color(DEFAULT_COLOR)
        return DEFAULT_COLOR

    if not save_color(chosen):
        log("[onboarding] Could not write the colour to .env; using it for this run only.")
    return chosen
