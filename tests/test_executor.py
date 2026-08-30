import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_pyautogui(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """This sandbox has no display, so pyautogui can't be imported for real —
    stub it in sys.modules before the executor imports it lazily."""
    fake = types.ModuleType("pyautogui")
    fake.click = MagicMock()
    fake.press = MagicMock()
    fake.scroll = MagicMock()
    fake.screenshot = MagicMock()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


from heypeer.capture.events import ActionEvent, ActionType  # noqa: E402
from heypeer.executor.runner import (  # noqa: E402
    ExecutionAborted,
    SkillRunner,
    create_file,
    create_folder,
    delete_file,
    move_single_file,
    rename_file,
    resolve_existing_filename,
)
from heypeer.patterns.skill import Skill  # noqa: E402


def _skill() -> Skill:
    return Skill(
        id="s1",
        name="test skill",
        actions=[
            ActionEvent(type=ActionType.CLICK, app_name="A", window_title="w", x=10, y=20),
            ActionEvent(
                type=ActionType.KEY_PRESS, app_name="A", window_title="w", key_name="enter"
            ),
        ],
    )


def test_run_replays_each_action_n_times(fake_pyautogui: MagicMock) -> None:
    runner = SkillRunner(step_delay=0)
    runner.run(_skill(), n_repetitions=3)

    assert fake_pyautogui.click.call_count == 3
    fake_pyautogui.click.assert_called_with(10, 20)
    assert fake_pyautogui.press.call_count == 3
    fake_pyautogui.press.assert_called_with("enter")


def test_run_aborts_on_failed_verification(fake_pyautogui: MagicMock) -> None:
    runner = SkillRunner(verify_step=lambda _png: False, step_delay=0)

    with pytest.raises(ExecutionAborted):
        runner.run(_skill(), n_repetitions=1)

    fake_pyautogui.click.assert_not_called()


def test_run_rejects_plain_character_key_press(fake_pyautogui: MagicMock) -> None:
    skill = Skill(
        id="s2",
        name="typed content skill",
        actions=[
            ActionEvent(
                type=ActionType.KEY_PRESS, app_name="A", window_title="w", key_name="char"
            )
        ],
    )
    runner = SkillRunner(step_delay=0)

    with pytest.raises(ExecutionAborted):
        runner.run(skill, n_repetitions=1)


def test_run_replays_file_move_skill_on_next_matching_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "Downloads"
    dest_dir = tmp_path / "Invoices"
    source_dir.mkdir()
    dest_dir.mkdir()

    for name in ["invoice_0.pdf", "invoice_1.pdf", "invoice_2.pdf", "invoice_3.pdf", "notes.txt"]:
        (source_dir / name).write_text("x")

    skill = Skill(
        id="sort_invoices",
        name="Move .pdf into Invoices",
        actions=[
            ActionEvent(
                type=ActionType.FILE_MOVE,
                app_name="",
                window_title=str(dest_dir),
                src_path=str(source_dir / "invoice_0.pdf"),
                dest_path=str(dest_dir / "invoice_0.pdf"),
            )
        ],
    )
    # invoice_0.pdf was already moved when the pattern was first observed —
    # simulate that by removing it from source_dir up front.
    (source_dir / "invoice_0.pdf").unlink()

    runner = SkillRunner(step_delay=0)
    runner.run(skill, n_repetitions=2)

    moved = sorted(p.name for p in dest_dir.iterdir())
    remaining = sorted(p.name for p in source_dir.iterdir())
    assert moved == ["invoice_1.pdf", "invoice_2.pdf"]
    assert remaining == ["invoice_3.pdf", "notes.txt"]


def test_run_file_move_skill_aborts_if_not_enough_matching_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "Downloads"
    dest_dir = tmp_path / "Invoices"
    source_dir.mkdir()
    dest_dir.mkdir()
    (source_dir / "invoice_1.pdf").write_text("x")

    skill = Skill(
        id="sort_invoices",
        name="Move .pdf into Invoices",
        actions=[
            ActionEvent(
                type=ActionType.FILE_MOVE,
                app_name="",
                window_title=str(dest_dir),
                src_path=str(source_dir / "invoice_0.pdf"),
                dest_path=str(dest_dir / "invoice_0.pdf"),
            )
        ],
    )

    runner = SkillRunner(step_delay=0)
    with pytest.raises(ExecutionAborted):
        runner.run(skill, n_repetitions=5)


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
