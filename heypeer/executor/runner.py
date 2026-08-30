"""Replays a Skill's actions via pyautogui, with an optional visual check
between steps to catch UI drift before it causes a wrong action.

FILE_MOVE skills are replayed differently: rather than pyautogui clicks, the
executor moves the next matching files (same directory + extension the
pattern was first observed on) directly via shutil — no window position or
screen state dependency at all.

`move_single_file`/`rename_file`/`create_file`/`create_folder`/`delete_file`
are the direct, one-off file operations Hey Peer can perform on a single
named file with no learned skill involved — Nemotron resolves which one and
which file/name(s) from the user's instruction (see
`heypeer/nemotron/client.py`), and `main.py` calls straight into these with
no confirmation step in between any more. `_ensure_within` is the safety
perimeter that replaces it for path *containment* (every target stays inside
the watched directory, no `../` escape) — `delete_file` additionally sends
to the recycle bin/trash rather than unlinking permanently, so at least
deletes stay reversible.
"""

import difflib
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from heypeer.capture.events import ActionEvent, ActionType
from heypeer.patterns.skill import Skill

# Injected by the caller (e.g. a Nemotron screenshot check). Receives the PNG
# bytes of a fresh screenshot taken right before the next action and returns
# whether it's safe to proceed.
VerifyStep = Callable[[bytes], bool]


class ExecutionAborted(RuntimeError):
    """Raised when a step-verification check fails mid-replay."""


class SkillRunner:
    def __init__(self, verify_step: VerifyStep | None = None, step_delay: float = 0.3) -> None:
        self.verify_step = verify_step
        self.step_delay = step_delay

    def _screenshot_png_bytes(self) -> bytes:
        import io

        import pyautogui

        buffer = io.BytesIO()
        pyautogui.screenshot().save(buffer, format="PNG")
        return buffer.getvalue()

    def _replay_action(self, action: ActionEvent) -> None:
        import pyautogui

        if action.type == ActionType.CLICK:
            if action.x is None or action.y is None:
                raise ExecutionAborted(f"Click action missing coordinates: {action}")
            pyautogui.click(action.x, action.y)
        elif action.type == ActionType.KEY_PRESS:
            if not action.key_name or action.key_name == "char":
                raise ExecutionAborted(
                    "Cannot replay a plain character key press — Hey Peer never "
                    "records typed content, only special keys (Enter, Tab, ...)."
                )
            pyautogui.press(action.key_name)
        elif action.type == ActionType.SCROLL:
            pyautogui.scroll(action.scroll_dy or 0)
        elif action.type in (ActionType.APP_FOCUS, ActionType.WINDOW_TITLE_CHANGE):
            pass  # Informational only — nothing to replay.

    def _run_file_move_skill(self, skill: Skill, n_repetitions: int) -> None:
        first = skill.actions[0]
        if not first.src_path or not first.dest_path:
            raise ExecutionAborted(f"File-move skill missing paths: {first}")

        source_dir = Path(first.src_path).parent
        dest_dir = Path(first.dest_path).parent
        extension = Path(first.src_path).suffix.lower()

        candidates = sorted(
            p
            for p in source_dir.iterdir()
            if p.is_file() and (not extension or p.suffix.lower() == extension)
        )
        if len(candidates) < n_repetitions:
            raise ExecutionAborted(
                f"Only {len(candidates)} matching file(s) left in {source_dir}, "
                f"need {n_repetitions}"
            )

        for path in candidates[:n_repetitions]:
            shutil.move(str(path), str(dest_dir / path.name))

    def run(self, skill: Skill, n_repetitions: int) -> None:
        if skill.actions and all(a.type == ActionType.FILE_MOVE for a in skill.actions):
            self._run_file_move_skill(skill, n_repetitions)
            return

        for _ in range(n_repetitions):
            for action in skill.actions:
                if self.verify_step is not None:
                    screenshot = self._screenshot_png_bytes()
                    if not self.verify_step(screenshot):
                        raise ExecutionAborted(
                            f"Visual verification failed before replaying {action}"
                        )
                self._replay_action(action)
                time.sleep(self.step_delay)


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


def _ensure_within(base: Path, target: Path, what: str) -> Path:
    """Resolves `target` and confirms it's actually inside `base` — the
    safety perimeter for every direct file operation Nemotron can trigger
    (move/rename/create/delete), since none of these go through a
    confirmation step any more. Guards against a hallucinated or
    adversarial name escaping the watched directory via '..' segments or
    an absolute path — `target` isn't required to exist yet (create_file/
    create_folder), `Path.resolve()` handles that fine."""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if not target_resolved.is_relative_to(base_resolved):
        raise ExecutionAborted(f"{what} would escape the watched directory: {target}")
    return target_resolved


def move_single_file(watched_dir: Path, src_filename: str, dest_folder: str) -> Path:
    """Direct, one-off file move for the "no skill needed, pure logic"
    assistant path — not tied to a learned Skill at all. Creates the
    destination folder if it doesn't exist yet. Returns the file's new
    path. Both `src_filename` and `dest_folder` are Nemotron-provided
    strings — resolved and checked against `watched_dir` before anything
    touches the filesystem."""
    resolved = resolve_existing_filename(watched_dir, src_filename)
    if resolved is None:
        raise ExecutionAborted(f"No file matching {src_filename!r} in {watched_dir}")
    src_path = _ensure_within(watched_dir, watched_dir / resolved, "source file")
    dest_dir = _ensure_within(watched_dir, watched_dir / dest_folder, "destination folder")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / src_path.name
    shutil.move(str(src_path), str(dest_path))
    return dest_path


def rename_file(watched_dir: Path, src_filename: str, new_name: str) -> Path:
    """Renames a file in place (same folder) — the "extend Hey Peer beyond
    move" direct-action path. `new_name` is checked the same way as
    `move_single_file`'s `dest_folder`."""
    resolved = resolve_existing_filename(watched_dir, src_filename)
    if resolved is None:
        raise ExecutionAborted(f"No file matching {src_filename!r} in {watched_dir}")
    src_path = _ensure_within(watched_dir, watched_dir / resolved, "source file")
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

    resolved = resolve_existing_filename(watched_dir, filename)
    if resolved is None:
        raise ExecutionAborted(f"No file matching {filename!r} in {watched_dir}")
    path = _ensure_within(watched_dir, watched_dir / resolved, "file to delete")
    send2trash(str(path))
    return path
