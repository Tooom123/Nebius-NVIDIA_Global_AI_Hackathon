"""The file operations Hey Peer can carry out on a single named file.

Move, rename, create and delete. Nemotron resolves which one and which
name(s) from the spoken instruction (see `heypeer/nemotron/client.py`) and
`main.py` calls straight in — there is no confirmation step.

`_ensure_within` is the safety perimeter that replaces it, for path
*containment*: every target resolves inside the watched directory, so a
misheard or hallucinated name cannot escape it via `../` or an absolute
path. `delete_file` additionally goes to the recycle bin rather than
unlinking, so at least deletes stay reversible (see `undo.py`).

This module once also replayed learned "skills" through pyautogui. That
whole idea is gone: in practice the skills learned from watching mouse and
keyboard activity never matched a spoken instruction, while the global input
hooks feeding them cost real performance on the user's machine.
"""

import difflib
import shutil
from pathlib import Path

from heypeer.executor import safe_zones


class ExecutionAborted(RuntimeError):
    """Raised when an action cannot be carried out safely."""


# Minimum similarity for a fuzzy filename match. High enough that unrelated
# files never match, loose enough to absorb a mistranscribed character
# ("15.xt" for "15.txt").
FILENAME_MATCH_THRESHOLD = 0.72


def resolve_existing_filename(watched_dir: Path, name: str) -> "str | None":
    """Maps a spoken filename onto a file that actually exists in
    `watched_dir`, or None.

    People say "le fichier 4", not "4.txt", and speech-to-text mangles short
    tokens ("15.xt"). Relying on the model to reconstruct the exact filename
    made real instructions fail outright — "renomme le fichier 4 en 15" was
    answered as unrecognized. Matching against the real listing here is both
    more reliable and cheaper than another model round trip.

    Tried in order of decreasing confidence: exact, case-insensitive, stem
    (the name without its extension), then fuzzy.
    """
    if not name or not watched_dir.is_dir():
        return None
    candidates = [p.name for p in watched_dir.iterdir() if p.is_file()]
    if not candidates:
        return None

    if name in candidates:
        return name

    lowered = name.lower()
    for candidate in candidates:
        if candidate.lower() == lowered:
            return candidate

    # "4" -> "4.txt". Only unambiguous matches count: if two files share the
    # stem ("4.txt" and "4.pdf"), guessing would be worse than declining.
    stem = Path(name).stem.lower()
    by_stem = [c for c in candidates if Path(c).stem.lower() == stem]
    if len(by_stem) == 1:
        return by_stem[0]

    # "facture" -> "facture_mars.pdf". People name a file by the part they
    # remember. Same unambiguity rule as above: several matches means
    # declining is safer than picking one.
    by_prefix = [c for c in candidates if Path(c).stem.lower().startswith(stem)]
    if len(by_prefix) == 1:
        return by_prefix[0]

    best = difflib.get_close_matches(name, candidates, n=1, cutoff=FILENAME_MATCH_THRESHOLD)
    return best[0] if best else None



def resolve_across_roots(watched_dir: Path, name: str) -> "Path | None":
    """Finds a spoken filename in the watched directory or any of the
    user's ordinary document folders, most likely first.

    File actions were confined to the watched directory until this; now
    that they are not, "supprime la capture" has to be able to mean a file
    on the Desktop. Search order is what disambiguates rather than a
    cleverer matcher: the first root holding a match wins, and the watched
    directory is always first, so nothing that worked before resolves
    differently now.

    An explicit path (absolute, or otherwise directly resolvable) is
    honoured as-is - the same rule `_resolve_code_path` follows in main.py.
    """
    candidate = Path(name).expanduser()
    if candidate.is_file():
        return candidate
    for root in safe_zones.search_roots(watched_dir):
        resolved = resolve_existing_filename(root, name)
        if resolved:
            return root / resolved
    return None

def _ensure_within(base: Path, target: Path, what: str) -> Path:
    """Resolves `target` and confirms a file action may touch it - the
    safety perimeter for every direct operation Nemotron can trigger
    (move/rename/create/delete), since none of these go through a
    confirmation step any more.

    The perimeter used to be `base` itself: everything had to resolve
    inside the watched directory. That was too narrow to be useful - real
    requests are about Documents, the Desktop, a project folder - so the
    boundary is now `executor/safe_zones.py`: the user's own files yes, the
    operating system's no. `base` is still accepted and still consulted
    first, because a *relative* name must keep resolving against the
    watched directory rather than the process's current directory, which
    is not somewhere the user has ever heard of.

    `target` isn't required to exist yet (create_file/create_folder);
    `Path.resolve()` handles that fine.
    """
    target_resolved = target.resolve()
    try:
        return safe_zones.ensure_allowed(target_resolved, what, extra_roots=[base])
    except safe_zones.OutsideSafeZone as exc:
        raise ExecutionAborted(str(exc)) from exc


def move_single_file(watched_dir: Path, src_filename: str, dest_folder: str) -> Path:
    """Direct, one-off file move for the "no skill needed, pure logic"
    assistant path — not tied to a learned Skill at all. Creates the
    destination folder if it doesn't exist yet. Returns the file's new
    path. Both `src_filename` and `dest_folder` are Nemotron-provided
    strings — resolved and checked against `watched_dir` before anything
    touches the filesystem."""
    found = resolve_across_roots(watched_dir, src_filename)
    if found is None:
        raise ExecutionAborted(f"No file matching {src_filename!r}")
    src_path = _ensure_within(watched_dir, found, "source file")
    # A bare destination name resolves beside the file being moved, not in
    # the watched directory: "range cette capture dans Archives" means an
    # Archives next to the capture, wherever that turned out to be.
    dest_candidate = Path(dest_folder).expanduser()
    if not dest_candidate.is_absolute():
        dest_candidate = src_path.parent / dest_folder
    dest_dir = _ensure_within(watched_dir, dest_candidate, "destination folder")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / src_path.name
    shutil.move(str(src_path), str(dest_path))
    return dest_path


def rename_file(watched_dir: Path, src_filename: str, new_name: str) -> Path:
    """Renames a file in place (same folder) — the "extend Hey Peer beyond
    move" direct-action path. `new_name` is checked the same way as
    `move_single_file`'s `dest_folder`."""
    found = resolve_across_roots(watched_dir, src_filename)
    if found is None:
        raise ExecutionAborted(f"No file matching {src_filename!r}")
    src_path = _ensure_within(watched_dir, found, "source file")
    # "renomme le fichier 4 en 15" means 4.txt -> 15.txt: people leave the
    # extension out when speaking, and silently dropping it would strip the
    # file's type.
    if not Path(new_name).suffix:
        new_name = new_name + src_path.suffix
    dest_path = _ensure_within(watched_dir, src_path.parent / new_name, "new file name")
    if dest_path.exists():
        raise ExecutionAborted(f"A file or folder named {new_name!r} already exists")
    src_path.rename(dest_path)
    return dest_path


def create_file(watched_dir: Path, name: str) -> Path:
    """Creates a new empty file under `watched_dir` (or a subfolder of it,
    if `name` includes one — e.g. "Archives/notes.txt")."""
    path = _ensure_within(watched_dir, watched_dir / name, "new file name")
    if path.exists():
        raise ExecutionAborted(f"A file or folder named {name!r} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def create_folder(watched_dir: Path, name: str) -> Path:
    """Creates a new folder under `watched_dir` (a no-op, not an error, if
    it already exists — creating a folder that's already there isn't a
    meaningful failure the way an existing *file* target would be)."""
    path = _ensure_within(watched_dir, watched_dir / name, "new folder name")
    path.mkdir(parents=True, exist_ok=True)
    return path


def delete_file(watched_dir: Path, filename: str) -> Path:
    """Deletes a file — to the recycle bin/trash (via `send2trash`), not a
    permanent unlink. There's no confirmation step before this runs any
    more, so keeping deletes reversible is the safety net that replaces it."""
    from send2trash import send2trash

    found = resolve_across_roots(watched_dir, filename)
    if found is None:
        raise ExecutionAborted(f"No file matching {filename!r}")
    path = _ensure_within(watched_dir, found, "file to delete")
    send2trash(str(path))
    return path
