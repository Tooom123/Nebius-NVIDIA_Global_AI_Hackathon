import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

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
from heypeer.executor.runner import ExecutionAborted, SkillRunner  # noqa: E402
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
