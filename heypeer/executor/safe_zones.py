"""Where file actions are allowed to reach.

## Why this replaces "the watched directory and nothing else"

Confining move/rename/create/delete to ~/Downloads was the right first
perimeter and the wrong permanent one. Real requests are about wherever the
user's files actually are - "range la facture dans Documents", "supprime la
capture sur le bureau", "renomme le rapport dans mon dossier projet" - and
a file assistant that only works in one folder is a demo of a file
assistant. `analyze_code`/`fix_code` already escaped this in round 40, for
the same reason, leaving file actions as the last thing still boxed in.

## Why this is not simply "anywhere"

The containment check exists because these actions run with no confirmation
step. A misheard "supprime les photos" that resolves somewhere in
C:\\Windows is not a hypothetical: fuzzy filename matching plus a speech
recogniser plus a language model is three independent chances to end up
somewhere nobody asked for.

So the perimeter widens rather than disappears: everything under the user's
own home directory is allowed, and a short list of places that are never
what someone means by voice is refused. The user's own files are the point;
the operating system's are not.

## Why a denylist inside home rather than an allowlist of folders

An allowlist (Documents, Desktop, Downloads, Pictures...) sounds safer and
is worse in practice: it breaks the moment someone keeps their work in
D:\\Projets or ~/dev, which is exactly the case that motivated widening
this. The rule is instead "your files yes, the system no", which is what a
person actually means.

Note this is a *containment* boundary, not a permission model. It stops an
instruction landing somewhere absurd. It does not stop the user deliberately
asking to delete their own file - undo and the recycle bin are what cover
that, and always were.
"""

import os
import sys
from pathlib import Path

# Directory names that are never what a spoken instruction means, matched
# case-insensitively anywhere in the resolved path. Deliberately short: a
# long list becomes a thing nobody maintains, and every entry here is a
# place where a wrong guess is unrecoverable rather than merely annoying.
FORBIDDEN_SEGMENTS = {
    "windows",
    "system32",
    "syswow64",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    # Unix equivalents, so this is coherent when developing off Windows.
    "/bin", "/sbin", "/usr", "/etc", "/var", "/boot", "/dev", "/proc", "/sys",
}

# Places inside the user's own home that hold application state rather than
# their documents. Losing these breaks software rather than losing work,
# and nobody asks a voice assistant to touch them by name.
FORBIDDEN_HOME_SUBPATHS = {
    "appdata",
    ".config",
    ".local",
    ".ssh",
    ".gnupg",
    ".aws",
    ".git",
}


class OutsideSafeZone(RuntimeError):
    """The resolved target is somewhere file actions must not reach."""


def home() -> Path:
    return Path.home().resolve()


def _is_system_path(resolved: Path) -> bool:
    parts_lower = [p.lower() for p in resolved.parts]
    for segment in FORBIDDEN_SEGMENTS:
        if segment.startswith("/"):
            # An absolute Unix root: only a prefix match counts, so a user's
            # own ~/dev/usr directory is not caught by "/usr".
            try:
                resolved.relative_to(segment)
                return True
            except ValueError:
                continue
        elif segment in parts_lower:
            return True
    return False


def _is_app_state_path(resolved: Path) -> bool:
    """Whether the path is application state rather than the user's work.

    Matched on any segment of the whole path, not just the part below
    `home()`. Found by a test: `~/.aws` on this machine is a symlink to
    `/mnt/c/Users/.../.aws`, so after `resolve()` it is no longer under
    home at all - it escaped the home-relative check and was then allowed
    by the rule that permits other drives. Symlinked config directories are
    completely ordinary (dotfile repos, WSL sharing a Windows home), so
    checking the resolved path's own segments is the honest test of what it
    actually is.
    """
    return any(part.lower() in FORBIDDEN_HOME_SUBPATHS for part in resolved.parts)


def is_allowed(target: Path, extra_roots: "list[Path] | None" = None) -> bool:
    """Whether a file action may touch `target`.

    `target` need not exist yet - create_file and create_folder name
    something that does not - so this resolves the path without requiring
    it, exactly as the old containment check did.

    `extra_roots` are additional locations to allow, whatever else this
    function would say about them. The watched directory is passed here:
    it is explicitly configured (HEYPEER_WATCHED_DIR), so wherever the user
    pointed it is by definition somewhere they meant, including a scratch
    directory outside home. Without this, configuring a watched folder on
    another drive would silently disable every file action.

    System paths are still refused even inside an extra root, since
    pointing the watched directory at C:\\Windows is a mistake rather than
    an intention.
    """
    try:
        resolved = Path(target).expanduser().resolve()
    except (OSError, RuntimeError):
        return False

    if _is_system_path(resolved) or _is_app_state_path(resolved):
        return False

    for root in extra_roots or []:
        try:
            resolved.relative_to(Path(root).expanduser().resolve())
            return True
        except (ValueError, OSError, RuntimeError):
            continue

    # The user's home is the ordinary case. Anything outside it is allowed
    # only if it is clearly a data location rather than the system: a second
    # drive, an external disk, a mounted share. On Windows that means any
    # drive root other than the system one; elsewhere, /mnt and /media.
    try:
        resolved.relative_to(home())
        return True
    except ValueError:
        pass

    if sys.platform == "win32":
        system_drive = (os.environ.get("SystemDrive") or "C:").lower()
        drive = resolved.drive.lower().rstrip("\\")
        return bool(drive) and drive != system_drive
    return any(str(resolved).startswith(prefix) for prefix in ("/mnt/", "/media/", "/Volumes/"))


def ensure_allowed(target: Path, what: str, extra_roots: "list[Path] | None" = None) -> Path:
    """Returns the resolved path, or raises `OutsideSafeZone` naming what
    was refused - the message is spoken back to the user, so it says where
    rather than just "no"."""
    resolved = Path(target).expanduser().resolve()
    if not is_allowed(resolved, extra_roots):
        raise OutsideSafeZone(
            f"{what} is outside the area Hey Peer may touch: {resolved}"
        )
    return resolved

# The folders a spoken "le fichier X" plausibly means, in the order they are
# searched. Ordinary places people keep documents, most-likely first.
# Deliberately not a recursive scan of the whole home directory: that is
# slow, and it makes a fuzzy name match against thousands of candidates,
# which is exactly how the wrong file gets picked.
COMMON_FOLDER_NAMES = (
    "Downloads", "Téléchargements", "Telechargements",
    "Desktop", "Bureau",
    "Documents",
    "Pictures", "Images",
    "Videos", "Vidéos",
    "Music", "Musique",
)


def search_roots(watched_dir: "Path | None" = None) -> "list[Path]":
    """Folders to look in when resolving a spoken filename, most likely
    first.

    The watched directory leads, since it is what the user explicitly
    configured and what every prior version of this project used. The usual
    document folders follow, under both their English and French names -
    Windows localises them, and which one exists depends on the install
    language rather than on anything Hey Peer can predict.
    """
    roots: "list[Path]" = []
    if watched_dir is not None and watched_dir.is_dir():
        roots.append(watched_dir.resolve())
    base = home()
    for name in COMMON_FOLDER_NAMES:
        candidate = base / name
        if candidate.is_dir():
            resolved = candidate.resolve()
            if resolved not in roots:
                roots.append(resolved)
    return roots
