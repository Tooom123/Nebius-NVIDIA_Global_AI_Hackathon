"""Tests for undo, the safety net that replaced the confirmation gate."""

from pathlib import Path

from heypeer.executor import undo


def test_stack_returns_the_most_recent_entry_first() -> None:
    stack = undo.UndoStack()
    stack.push(undo.UndoEntry(description="first", undo=lambda: None))
    stack.push(undo.UndoEntry(description="second", undo=lambda: None))

    assert stack.pop().description == "second"
    assert stack.pop().description == "first"
    assert stack.pop() is None


def test_stack_is_bounded() -> None:
    """'Annule' always means the last action; an unbounded stack would keep
    stale paths alive forever."""
    stack = undo.UndoStack(max_entries=3)
    for i in range(10):
        stack.push(undo.UndoEntry(description=str(i), undo=lambda: None))

    assert len(stack) == 3
    assert stack.pop().description == "9"


def test_undo_move_puts_the_file_back(tmp_path: Path) -> None:
    src = tmp_path / "facture.pdf"
    dest_dir = tmp_path / "Archives"
    dest_dir.mkdir()
    dest = dest_dir / "facture.pdf"
    dest.write_text("x")

    undo.moved(src, dest).undo()

    assert src.is_file()
    assert not dest.exists()


def test_undo_move_recreates_a_missing_source_folder(tmp_path: Path) -> None:
    """The original folder can have been removed in between; undo shouldn't
    fail because of that."""
    src = tmp_path / "gone" / "facture.pdf"
    dest = tmp_path / "facture.pdf"
    dest.write_text("x")

    undo.moved(src, dest).undo()

    assert src.is_file()


def test_undo_rename_restores_the_old_name(tmp_path: Path) -> None:
    src = tmp_path / "4.txt"
    dest = tmp_path / "15.txt"
    dest.write_text("x")

    undo.renamed(src, dest).undo()

    assert src.is_file()
    assert not dest.exists()


def test_undo_create_file_removes_it(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.touch()

    undo.created_file(path).undo()

    assert not path.exists()


def test_undo_create_file_keeps_a_file_the_user_has_written_to(tmp_path: Path) -> None:
    """Hey Peer created it empty. If there's content now, someone put it
    there, and undo must not destroy it."""
    path = tmp_path / "notes.txt"
    path.write_text("the user typed this")

    undo.created_file(path).undo()

    assert path.is_file()
    assert path.read_text() == "the user typed this"


def test_undo_create_folder_removes_it_when_empty(tmp_path: Path) -> None:
    path = tmp_path / "Factures"
    path.mkdir()

    undo.created_folder(path).undo()

    assert not path.exists()


def test_undo_create_folder_keeps_a_folder_with_files_in_it(tmp_path: Path) -> None:
    """Undoing a folder creation must never take files with it."""
    path = tmp_path / "Factures"
    path.mkdir()
    (path / "facture.pdf").write_text("x")

    undo.created_folder(path).undo()

    assert path.is_dir()
    assert (path / "facture.pdf").is_file()


def test_delete_is_recorded_as_not_undoable_with_a_reason(tmp_path: Path) -> None:
    """send2trash deliberately offers no programmatic restore, so this says
    where the file went rather than pretending it can bring it back."""
    entry = undo.deleted(tmp_path / "notes.txt")

    assert entry.undo is None
    assert "corbeille" in entry.not_undoable_reason
