import sys
import types
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
