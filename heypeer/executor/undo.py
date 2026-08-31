"""Undo for the direct file actions.

There is no confirmation step before an action runs any more — that was
removed because misheard yes/no replies blocked legitimate work more often
than they prevented mistakes. Undo is the safety net that replaces it, and a
better-shaped one: it costs nothing when Hey Peer gets it right, and only
asks for attention when it doesn't.

Every action records how to reverse itself at the moment it succeeds, when
the exact paths involved are known. Reconstructing that afterwards from the
intent would be guesswork — the resolved filename, the created folder, the
extension inherited during a rename are all decided inside the executor.

Deletes are the honest exception. They go to the recycle bin via
`send2trash`, which deliberately offers no programmatic restore, so
`UndoStack` records them as *not* undoable and says where the file went
instead of pretending. That is still better than a permanent unlink, which
is why deletes work that way in the first place.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Only the most recent actions are worth keeping: "annule" always means the
# last one, and an unbounded stack would keep stale paths alive forever.
MAX_ENTRIES = 10


@dataclass
class UndoEntry:
    """One reversible action. `description` is spoken back to the user, so it
    is phrased in French, from Hey Peer's point of view."""

    description: str
    undo: "Callable[[], None] | None"  # None = happened, but can't be reversed
    not_undoable_reason: str | None = None


class UndoStack:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._entries: list[UndoEntry] = []
        self._max_entries = max_entries

    def push(self, entry: UndoEntry) -> None:
        self._entries.append(entry)
        del self._entries[: -self._max_entries]

    def pop(self) -> "UndoEntry | None":
        return self._entries.pop() if self._entries else None

    def __len__(self) -> int:
        return len(self._entries)


def moved(src: Path, dest: Path) -> UndoEntry:
    """Reverses a move by moving the file back to where it came from."""

    def undo() -> None:
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(src))

    return UndoEntry(description=f"le déplacement de {src.name}", undo=undo)


def renamed(src: Path, dest: Path) -> UndoEntry:
    def undo() -> None:
        dest.rename(src)

    return UndoEntry(description=f"le renommage de {src.name}", undo=undo)


def created_file(path: Path) -> UndoEntry:
    """Reverses a creation by removing what was created. Safe because the
    file was empty when Hey Peer made it — but it checks, so an undo issued
    after the user has typed something into it can't destroy their work."""

    def undo() -> None:
        if path.is_file() and path.stat().st_size == 0:
            path.unlink()

    return UndoEntry(description=f"la création de {path.name}", undo=undo)


def created_folder(path: Path) -> UndoEntry:
    """Only removes the folder if it is still empty — undoing a folder
    creation must never take files with it."""

    def undo() -> None:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()

    return UndoEntry(description=f"la création du dossier {path.name}", undo=undo)


def code_fixed(path: Path, original_content: str) -> UndoEntry:
    """Reverses an agent-applied code fix by restoring the file's exact
    content from before the agent touched it.

    This is the safety net for `fix_code` in place of a confirmation step,
    same reasoning as every other action here - except a code edit has no
    recycle bin to fall back on the way a delete does, so the *whole*
    content is captured and restored outright rather than reasoned about
    afterwards, which would mean re-deriving what changed from a diff.
    """

    def undo() -> None:
        path.write_text(original_content, encoding="utf-8")

    return UndoEntry(description=f"la modification de {path.name}", undo=undo)


def deleted(path: Path) -> UndoEntry:
    return UndoEntry(
        description=f"la suppression de {path.name}",
        undo=None,
        not_undoable_reason=(
            f"{path.name} est dans la corbeille, tu peux le restaurer depuis là"
        ),
    )
