"""Where things live, whether running from a checkout or a frozen build.

## The problem this solves

Modules across this project locate files by walking up from `__file__` to
the repo root - the wake-word model, the Piper voices, the activation
chime, `memory.json`, `routines.json`. That is correct from a git checkout
and wrong in a PyInstaller build two different ways at once, because the
paths fall into two categories that a frozen app must treat differently:

* **Bundled resources** (the wake-word model, the chime, the voices) ship
  inside the executable and are unpacked to a temporary directory that
  PyInstaller exposes as `sys._MEIPASS`. That directory is read-only for
  practical purposes and is deleted when the app exits.
* **User data** (remembered facts, routines) must outlive the process and
  be writable. Writing it into `sys._MEIPASS` would appear to work and then
  silently vanish on every restart - the worst kind of bug, since nothing
  errors.

Resolving both through one "project root" would put user data in the
temporary unpack directory. So there are two functions, and callers pick
the one that matches what they are asking for.

## Why not just always use the user directory

From a checkout, `data/` next to the source *is* the right place: it is
what the tests, the training scripts and the developer's own workflow
already use, and moving it to `%LOCALAPPDATA%` would strand the wake-word
model someone just trained. Frozen builds are the only case that needs
somewhere else, so that is the only case that gets it.
"""

import os
import sys
from pathlib import Path

APP_NAME = "HeyPeer"


def is_frozen() -> bool:
    """Whether this is running from a PyInstaller-style bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def resource_root() -> Path:
    """Where read-only files that ship with the app live.

    In a frozen build this is PyInstaller's unpack directory; from a
    checkout it is the repo root. Never write here: in a frozen build the
    directory is deleted when the process exits.
    """
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Where files the user accumulates live - writable, and surviving both
    a restart and an app update.

    From a checkout this is `data/` beside the source, which is what the
    rest of the project already expects. In a frozen build it is a
    per-user application-data directory, because there is no source tree to
    sit beside and the unpack directory does not survive the process.

    `HEYPEER_DATA_DIR` overrides both, which is what the tests use rather
    than reaching into either branch.
    """
    override = os.environ.get("HEYPEER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if is_frozen():
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
            return Path(base) / APP_NAME
        return Path.home() / f".{APP_NAME.lower()}"
    return Path(__file__).resolve().parent.parent / "data"


def resource(*parts: str) -> Path:
    """A bundled resource, by path segments under `resource_root()`."""
    return resource_root().joinpath(*parts)


def user_data(*parts: str) -> Path:
    """A user-data file, by path segments under `data_root()`."""
    return data_root().joinpath(*parts)
