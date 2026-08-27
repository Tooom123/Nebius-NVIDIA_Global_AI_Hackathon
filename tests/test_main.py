import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from heypeer.main import HeyPeer
from heypeer.nemotron.intent import Intent
from heypeer.patterns.detector import PatternDetector
from heypeer.patterns.memory import SkillMemory
from heypeer.patterns.skill import Skill


@pytest.fixture
def fake_pyautogui(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake = types.ModuleType("pyautogui")
    fake.click = MagicMock()
    fake.press = MagicMock()
    fake.scroll = MagicMock()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


def _peer(tmp_path: Path, nemotron: MagicMock) -> HeyPeer:
    memory = SkillMemory(tmp_path / "skills.json")
    memory.add(Skill(id="sort_files", name="Sort downloaded files", actions=[]))
    return HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "do it 4 more times",
    )


def test_on_wake_word_runs_confirmed_skill(tmp_path: Path, fake_pyautogui: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="run_skill", skill_id="sort_files", n_repetitions=2
    )
    nemotron.verify_screen.return_value = True
    peer = _peer(tmp_path, nemotron)

    with patch("heypeer.main.confirm", return_value=True):
        peer.on_wake_word()

    nemotron.interpret_text.assert_called_once()
    call_args = nemotron.interpret_text.call_args.args
    assert call_args[0] == "do it 4 more times"
    assert {"id": "sort_files", "name": "Sort downloaded files"} in call_args[1]


def test_on_wake_word_skips_execution_if_not_confirmed(
    tmp_path: Path, fake_pyautogui: MagicMock
) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="run_skill", skill_id="sort_files", n_repetitions=2
    )
    peer = _peer(tmp_path, nemotron)

    with patch("heypeer.main.confirm", return_value=False):
        peer.on_wake_word()

    fake_pyautogui.click.assert_not_called()


def test_on_wake_word_handles_unknown_intent(tmp_path: Path, fake_pyautogui: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(action="unknown", skill_id=None, n_repetitions=1)
    peer = _peer(tmp_path, nemotron)

    peer.on_wake_word()  # should not raise, no confirmation prompt reached

    fake_pyautogui.click.assert_not_called()
