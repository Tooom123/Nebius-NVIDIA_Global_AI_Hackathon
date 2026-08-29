import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from heypeer.capture.events import ActionEvent, ActionType
from heypeer.main import _SHUTDOWN, HeyPeer
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


def test_input_events_and_file_events_use_separate_detectors(tmp_path: Path) -> None:
    """Regression test: mouse/keyboard noise during a drag-and-drop must not
    interfere with — or be confused for — the file-move pattern, and vice
    versa. Each event source has to feed its own PatternDetector."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)

    # Two clicks in the same app/window: on its own this is below the
    # min_repetitions=3 default threshold for the *input* detector.
    for _ in range(2):
        peer._on_input_event(
            ActionEvent(type=ActionType.CLICK, app_name="Explorer", window_title="w", x=1, y=1)
        )
    assert len(peer.memory.all()) == 1  # still just the seeded "sort_files" skill

    # A third click interleaved with file-move events must not let a mixed
    # (click + file-move) sequence satisfy either detector.
    peer._on_input_event(
        ActionEvent(type=ActionType.CLICK, app_name="Explorer", window_title="w", x=1, y=1)
    )
    for i in range(3):
        peer._on_file_event(
            ActionEvent(
                type=ActionType.FILE_MOVE,
                app_name="",
                window_title="/dest",
                src_path=f"/watched/f{i}.pdf",
                dest_path=f"/dest/f{i}.pdf",
            )
        )

    skills = {s.id: s for s in peer.memory.all()}
    assert "sort_files" in skills
    file_skills = [s for s in skills.values() if s.id != "sort_files"]
    assert len(file_skills) == 1
    assert all(a.type == ActionType.FILE_MOVE for a in file_skills[0].actions)


def test_move_file_intent_moves_the_named_file(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="move_file",
        skill_id=None,
        n_repetitions=1,
        src_filename="facture.pdf",
        dest_folder="Archives",
    )
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        watched_dir=watched_dir,
        get_instruction=lambda: "déplace facture.pdf vers Archives",
    )

    with patch("heypeer.main.confirm", return_value=True):
        peer.on_wake_word()

    assert (watched_dir / "Archives" / "facture.pdf").exists()
    assert not (watched_dir / "facture.pdf").exists()


def test_auto_mode_toggle_does_not_affect_capture(tmp_path: Path) -> None:
    """Capture (skill learning) is native/always-on and must not be started
    or stopped by the voice-activation ("Mode auto") toggle."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer.watcher.start = MagicMock()
    peer.watcher.stop = MagicMock()

    peer.start_capture()
    peer.watcher.start.assert_called_once()

    with patch.object(peer, "_run_wake_listener"):
        peer._set_auto_mode(True)
        peer._set_auto_mode(False)

    peer.watcher.stop.assert_not_called()

    peer.stop_capture()
    peer.watcher.stop.assert_called_once()


def test_move_file_intent_cancelled_does_not_move(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="move_file",
        skill_id=None,
        n_repetitions=1,
        src_filename="facture.pdf",
        dest_folder="Archives",
    )
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        watched_dir=watched_dir,
        get_instruction=lambda: "déplace facture.pdf vers Archives",
    )

    with patch("heypeer.main.confirm", return_value=False):
        peer.on_wake_word()

    assert (watched_dir / "facture.pdf").exists()
    assert not (watched_dir / "Archives").exists()


def test_on_wake_detected_only_enqueues_does_not_call_get_instruction(tmp_path: Path) -> None:
    """Regression test: the wake-word audio thread's on_detected callback
    must stay cheap and non-blocking. Handling the instruction inline (i.e.
    calling get_instruction()/input() from that thread) was found to not
    actually wait for keyboard input on Windows."""
    nemotron = MagicMock()
    get_instruction = MagicMock(return_value="do it 4 more times")
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=get_instruction,
    )

    peer._on_wake_detected()

    get_instruction.assert_not_called()
    assert peer._detections.get_nowait() is None


def test_on_quit_enqueues_shutdown_sentinel(tmp_path: Path) -> None:
    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)

    peer._on_quit()

    assert peer._detections.get_nowait() is _SHUTDOWN


def test_log_prints_and_forwards_to_debug_window(tmp_path: Path) -> None:
    nemotron = MagicMock()
    debug_window = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory, detector=PatternDetector(), nemotron=nemotron, debug_window=debug_window
    )

    peer._log("hello")

    debug_window.log.assert_called_once_with("hello")
