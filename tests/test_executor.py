from pathlib import Path
from unittest.mock import patch

import pytest


from heypeer.executor.runner import (  # noqa: E402
    ExecutionAborted,
    create_file,
    create_folder,
    delete_file,
    move_single_file,
    rename_file,
    resolve_existing_filename,
)


def test_move_single_file_creates_dest_dir_and_moves(tmp_path: Path) -> None:
    (tmp_path / "facture.pdf").write_text("x")

    result = move_single_file(tmp_path, "facture.pdf", "Archives")

    assert result == tmp_path / "Archives" / "facture.pdf"
    assert result.exists()
    assert not (tmp_path / "facture.pdf").exists()


def test_move_single_file_missing_source_aborts(tmp_path: Path) -> None:
    with pytest.raises(ExecutionAborted):
        move_single_file(tmp_path, "does_not_exist.pdf", "Archives")


def test_move_single_file_rejects_dest_folder_escaping_watched_dir(tmp_path: Path) -> None:
    (tmp_path / "facture.pdf").write_text("x")

    with pytest.raises(ExecutionAborted):
        move_single_file(tmp_path, "facture.pdf", "../outside")

    assert (tmp_path / "facture.pdf").exists()  # never touched


def test_rename_file_renames_in_place(tmp_path: Path) -> None:
    (tmp_path / "facture.pdf").write_text("x")

    result = rename_file(tmp_path, "facture.pdf", "facture_mars.pdf")

    assert result == tmp_path / "facture_mars.pdf"
    assert result.exists()
    assert not (tmp_path / "facture.pdf").exists()


def test_rename_file_missing_source_aborts(tmp_path: Path) -> None:
    with pytest.raises(ExecutionAborted):
        rename_file(tmp_path, "does_not_exist.pdf", "new_name.pdf")


def test_rename_file_rejects_existing_target(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_text("x")
    (tmp_path / "b.pdf").write_text("y")

    with pytest.raises(ExecutionAborted):
        rename_file(tmp_path, "a.pdf", "b.pdf")


def test_rename_file_rejects_new_name_escaping_watched_dir(tmp_path: Path) -> None:
    (tmp_path / "facture.pdf").write_text("x")

    with pytest.raises(ExecutionAborted):
        rename_file(tmp_path, "facture.pdf", "../escaped.pdf")


def test_create_file_creates_empty_file(tmp_path: Path) -> None:
    result = create_file(tmp_path, "notes.txt")

    assert result == tmp_path / "notes.txt"
    assert result.is_file()
    assert result.read_text() == ""


def test_create_file_rejects_existing_target(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("existing")

    with pytest.raises(ExecutionAborted):
        create_file(tmp_path, "notes.txt")


def test_create_file_rejects_name_escaping_watched_dir(tmp_path: Path) -> None:
    with pytest.raises(ExecutionAborted):
        create_file(tmp_path, "../escaped.txt")


def test_create_folder_creates_new_folder(tmp_path: Path) -> None:
    result = create_folder(tmp_path, "Factures")

    assert result == tmp_path / "Factures"
    assert result.is_dir()


def test_create_folder_is_a_noop_if_already_present(tmp_path: Path) -> None:
    (tmp_path / "Factures").mkdir()

    result = create_folder(tmp_path, "Factures")  # must not raise

    assert result.is_dir()


def test_create_folder_rejects_name_escaping_watched_dir(tmp_path: Path) -> None:
    with pytest.raises(ExecutionAborted):
        create_folder(tmp_path, "../escaped")


def test_delete_file_sends_to_trash_not_permanent_unlink(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x")

    with patch("send2trash.send2trash") as fake_trash:
        result = delete_file(tmp_path, "notes.txt")

    fake_trash.assert_called_once_with(str(tmp_path / "notes.txt"))
    assert result == tmp_path / "notes.txt"


def test_delete_file_missing_file_aborts(tmp_path: Path) -> None:
    with pytest.raises(ExecutionAborted):
        delete_file(tmp_path, "does_not_exist.txt")


def test_delete_file_rejects_name_escaping_watched_dir(tmp_path: Path) -> None:
    with pytest.raises(ExecutionAborted):
        delete_file(tmp_path, "../escaped.txt")


def test_resolve_matches_a_spoken_name_without_its_extension(tmp_path: Path) -> None:
    """Regression test for a real failure: "renomme le fichier 4 en 15" was
    answered as unrecognized because people say "4", not "4.txt"."""
    (tmp_path / "4.txt").write_text("x")

    assert resolve_existing_filename(tmp_path, "4") == "4.txt"


def test_resolve_absorbs_a_mistranscribed_character(tmp_path: Path) -> None:
    (tmp_path / "15.txt").write_text("x")

    assert resolve_existing_filename(tmp_path, "15.xt") == "15.txt"


def test_resolve_is_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "Facture_Mars.pdf").write_text("x")

    assert resolve_existing_filename(tmp_path, "facture_mars.pdf") == "Facture_Mars.pdf"


def test_resolve_matches_a_remembered_prefix(tmp_path: Path) -> None:
    (tmp_path / "facture_mars.pdf").write_text("x")
    (tmp_path / "notes.txt").write_text("x")

    assert resolve_existing_filename(tmp_path, "facture") == "facture_mars.pdf"


def test_resolve_declines_when_ambiguous(tmp_path: Path) -> None:
    """Two files share the stem, so guessing one would be worse than
    declining and letting the user rephrase."""
    (tmp_path / "4.txt").write_text("x")
    (tmp_path / "4.pdf").write_text("x")

    assert resolve_existing_filename(tmp_path, "4") is None


def test_resolve_declines_on_an_unrelated_name(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x")

    assert resolve_existing_filename(tmp_path, "quarterly_report") is None


def test_rename_inherits_the_extension_when_the_new_name_has_none(tmp_path: Path) -> None:
    (tmp_path / "4.txt").write_text("x")

    result = rename_file(tmp_path, "4", "15")

    assert result.name == "15.txt"
    assert result.is_file()


def test_rename_keeps_an_explicit_new_extension(tmp_path: Path) -> None:
    (tmp_path / "4.txt").write_text("x")

    result = rename_file(tmp_path, "4.txt", "notes.md")

    assert result.name == "notes.md"
