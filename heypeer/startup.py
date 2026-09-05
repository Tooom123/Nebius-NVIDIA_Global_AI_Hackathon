"""Run Hey Peer automatically at login, on Windows.

An always-on assistant that has to be started by hand every morning is not
always-on. This is the last piece of that claim.

## Why a Startup-folder shortcut, not a registry Run key or a service

All three work. The shortcut is the one the user can see, move, and delete
without regedit or an admin prompt: it is a file in a folder Explorer opens
with `shell:startup`. For something that runs silently at every login, being
easy to *turn off* by someone who has forgotten this module exists matters
more than being tidy.

A Windows service was rejected outright: it would run outside the user's
desktop session, where the tray icon, the overlay and the microphone all
live.

## Why `.lnk` through COM rather than a .bat

A batch file in Startup flashes a console window at every login. A shortcut
does not, and it can also carry a working directory and a "minimised" hint.
Creating one needs the Windows Script Host COM object - hence `pywin32` or
`comtypes` - so this degrades honestly when neither is installed rather than
writing a worse thing silently.

## Frozen builds vs. a checkout

A frozen build is one file, so the shortcut points at the executable. From
a checkout it has to point at the interpreter with `-m heypeer.main`, and
at the right interpreter - `sys.executable` inside a virtualenv is that
virtualenv's python, which is exactly what is wanted, since the system
python will not have this project's dependencies.
"""

import os
import platform
import sys
from pathlib import Path

SHORTCUT_NAME = "Hey Peer.lnk"


class StartupUnavailable(RuntimeError):
    """Cannot manage the login entry - not Windows, or no COM library."""


def is_supported() -> bool:
    return platform.system() == "Windows"


def startup_dir() -> Path:
    """The per-user Startup folder. Per-user rather than the all-users one
    on purpose: this needs no elevation, and Hey Peer is a personal
    assistant with one person's wake-word model and one person's memory."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise StartupUnavailable("APPDATA is not set; is this Windows?")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def launch_command() -> "tuple[str, str, str]":
    """`(target, arguments, working_directory)` for the shortcut.

    Split out from `enable` so it can be asserted on in a test without
    creating anything or needing Windows.
    """
    if getattr(sys, "frozen", False):
        # One file: it is its own launcher, and its directory is a sensible
        # working directory.
        return (sys.executable, "", str(Path(sys.executable).parent))
    # A checkout: this interpreter (the project's virtualenv, if there is
    # one) running the package, from the project root so relative paths and
    # the .env file resolve the way they do when started by hand.
    project_root = Path(__file__).resolve().parent.parent
    return (sys.executable, "-m heypeer.main", str(project_root))


def is_enabled() -> bool:
    try:
        return shortcut_path().is_file()
    except StartupUnavailable:
        return False


def enable() -> Path:
    """Creates the login shortcut, replacing any existing one - so this
    doubles as "repair it after the project moved". Returns its path."""
    if not is_supported():
        raise StartupUnavailable("run-at-login is only implemented for Windows")

    target, arguments, working_dir = launch_command()
    path = shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import pythoncom  # noqa: F401
        from win32com.client import Dispatch
    except ImportError:
        try:
            from comtypes.client import CreateObject as Dispatch  # type: ignore
        except ImportError as exc:
            raise StartupUnavailable(
                "creating a shortcut needs pywin32 or comtypes: pip install pywin32"
            ) from exc

    shell = Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(path))
    shortcut.TargetPath = target
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = working_dir
    shortcut.Description = "Hey Peer - voice assistant"
    shortcut.WindowStyle = 7  # minimised, so a console build does not pop up
    shortcut.Save()
    return path


def disable() -> bool:
    """Removes the login shortcut. Returns whether there was one - so the
    caller can tell "turned it off" from "it was already off"."""
    if not is_supported():
        raise StartupUnavailable("run-at-login is only implemented for Windows")
    path = shortcut_path()
    if not path.is_file():
        return False
    path.unlink()
    return True


def main(argv: "list[str] | None" = None) -> int:
    """`python -m heypeer.startup [enable|disable|status]`."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m heypeer.startup",
        description="Manage whether Hey Peer starts automatically at login (Windows).",
    )
    parser.add_argument("action", choices=["enable", "disable", "status"], nargs="?", default="status")
    args = parser.parse_args(argv)

    try:
        if args.action == "enable":
            print(f"Hey Peer will start at login: {enable()}")
        elif args.action == "disable":
            print("Removed from login startup." if disable() else "It was not set to start at login.")
        else:
            print("Starts at login." if is_enabled() else "Does not start at login.")
    except StartupUnavailable as exc:
        print(f"Cannot manage login startup: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
