import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from heypeer.capture.events import ActionEvent, ActionType
from heypeer.main import _SHUTDOWN, HeyPeer
from heypeer.nemotron.intent import Intent
from heypeer.patterns.detector import PatternDetector
from heypeer.patterns.memory import SkillMemory
from heypeer.patterns.skill import Skill


@pytest.fixture(autouse=True)
def fake_tts(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Avoids loading a real Piper voice / touching an audio output device
    on every test that reaches a spoken narration."""
    speak_mock = MagicMock()
    monkeypatch.setattr("heypeer.tray.tts.speak", speak_mock, raising=False)
    return speak_mock


@pytest.fixture
def fake_pyautogui(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake = types.ModuleType("pyautogui")
    fake.click = MagicMock()
    fake.press = MagicMock()
    fake.scroll = MagicMock()
    fake.screenshot = MagicMock(return_value=MagicMock(save=MagicMock()))
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


def test_on_wake_word_runs_skill_directly_no_confirmation(
    tmp_path: Path, fake_pyautogui: MagicMock, fake_tts: MagicMock
) -> None:
    """No confirmation gate any more - a resolved run_skill intent executes
    immediately (removed per explicit user feedback that it caused more
    problems than it solved)."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="run_skill", skill_id="sort_files", n_repetitions=2
    )
    nemotron.verify_screen.return_value = True
    peer = _peer(tmp_path, nemotron)

    peer.on_wake_word()

    nemotron.interpret_text.assert_called_once()
    call_args = nemotron.interpret_text.call_args.args
    assert call_args[0] == "do it 4 more times"
    assert {"id": "sort_files", "name": "Sort downloaded files"} in call_args[1]
    # Spoken once before executing (narration) and again once done.
    assert fake_tts.call_count == 2


def test_on_wake_word_handles_unknown_intent(tmp_path: Path, fake_pyautogui: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(action="unknown", skill_id=None, n_repetitions=1)
    peer = _peer(tmp_path, nemotron)

    peer.on_wake_word()  # should not raise

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


def _peer_with_watched_dir(tmp_path: Path, nemotron: MagicMock, watched_dir: Path) -> HeyPeer:
    memory = SkillMemory(tmp_path / "skills.json")
    return HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        watched_dir=watched_dir,
        get_instruction=lambda: "instruction",
    )


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
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    peer.on_wake_word()

    assert (watched_dir / "Archives" / "facture.pdf").exists()
    assert not (watched_dir / "facture.pdf").exists()


def test_watched_folders_are_passed_to_nemotron(tmp_path: Path) -> None:
    """Regression test: Nemotron needs to know what folders already exist
    to reuse a real one instead of inventing a variant of a stated name
    (real bug: "test" -> created "tests")."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "test").mkdir()
    (watched_dir / "facture.pdf").write_text("x")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(action="unknown", skill_id=None, n_repetitions=1)
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    peer.on_wake_word()

    assert nemotron.interpret_text.call_args.kwargs["watched_folders"] == ["test"]


def test_rename_file_intent_renames_the_named_file(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="rename_file",
        skill_id=None,
        n_repetitions=1,
        src_filename="facture.pdf",
        new_name="facture_mars.pdf",
    )
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    peer.on_wake_word()

    assert (watched_dir / "facture_mars.pdf").exists()
    assert not (watched_dir / "facture.pdf").exists()


def test_create_folder_intent_creates_the_named_folder(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="create_folder", skill_id=None, n_repetitions=1, target_name="Factures"
    )
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    peer.on_wake_word()

    assert (watched_dir / "Factures").is_dir()


def test_create_file_intent_creates_the_named_file(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="create_file", skill_id=None, n_repetitions=1, target_name="notes.txt"
    )
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    peer.on_wake_word()

    assert (watched_dir / "notes.txt").is_file()


def test_delete_file_intent_deletes_the_named_file(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "notes.txt").write_text("x")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="delete_file", skill_id=None, n_repetitions=1, src_filename="notes.txt"
    )
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    with patch("send2trash.send2trash") as fake_trash:
        peer.on_wake_word()

    fake_trash.assert_called_once()


def test_file_action_failure_does_not_raise(tmp_path: Path) -> None:
    """A missing source file (ExecutionAborted) must be caught and logged,
    not propagate - there's no confirmation step any more to have gated it
    beforehand."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="move_file",
        skill_id=None,
        n_repetitions=1,
        src_filename="does_not_exist.pdf",
        dest_folder="Archives",
    )
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    peer.on_wake_word()  # must not raise


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

    fake_audio = MagicMock()
    peer._on_wake_detected(fake_audio)

    get_instruction.assert_not_called()
    assert peer._detections.get_nowait() is fake_audio


def test_on_quit_enqueues_shutdown_sentinel(tmp_path: Path) -> None:
    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)

    peer._on_quit()

    assert peer._detections.get_nowait() is _SHUTDOWN


def test_on_wake_detected_mutes_the_listener_immediately(tmp_path: Path) -> None:
    """Regression test: real logs showed the audio thread picking up a
    second "Hey Peer" (or ambient chatter) while the first instruction was
    still being transcribed/interpreted - muting now starts the instant a
    detection comes in, not just around the later TTS-playback window."""
    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)
    peer._wake_listener = MagicMock()

    peer._on_wake_detected(np.zeros(1600, dtype=np.int16))

    peer._wake_listener.mute.assert_called_once()
    peer._wake_listener.unmute.assert_not_called()


def test_on_wake_word_unmutes_the_listener_once_the_whole_turn_is_done(
    tmp_path: Path, fake_pyautogui: MagicMock
) -> None:
    """The listener stays muted through transcribe -> interpret -> execute ->
    speak, unmuted only at the very end of the turn - not right after
    speaking, and not right after interpreting."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(action="unknown", skill_id=None, n_repetitions=1)
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "typed instruction",
    )
    peer._wake_listener = MagicMock()

    peer.on_wake_word()

    peer._wake_listener.unmute.assert_called_once()


def test_on_wake_word_unmutes_even_if_interpretation_fails(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.side_effect = RuntimeError("network error")
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "typed instruction",
    )
    peer._wake_listener = MagicMock()

    peer.on_wake_word()  # must not raise

    peer._wake_listener.unmute.assert_called_once()


def test_on_wake_word_with_audio_transcribes_locally_then_uses_interpret_text(
    tmp_path: Path, fake_pyautogui: MagicMock
) -> None:
    """Real recorded audio is transcribed locally (Nemotron via this Nebius
    endpoint doesn't accept audio input - see nemotron/client.py's module
    docstring) and the resulting text, with a screenshot, goes through
    interpret_text() - no fallback to typed input()."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="run_skill", skill_id="sort_files", n_repetitions=1
    )
    get_instruction = MagicMock(return_value="should not be called")
    memory = SkillMemory(tmp_path / "skills.json")
    memory.add(Skill(id="sort_files", name="Sort downloaded files", actions=[]))
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=get_instruction,
    )
    audio = np.zeros(16000, dtype=np.int16)

    with patch("heypeer.wakeword.stt.transcribe", return_value="do it again"):
        peer.on_wake_word(audio)

    get_instruction.assert_not_called()
    nemotron.interpret_text.assert_called_once()
    call_args = nemotron.interpret_text.call_args
    assert call_args.args[0] == "do it again"
    assert call_args.kwargs["screenshot_path"] is not None


def test_on_wake_word_with_empty_audio_falls_back_to_text(
    tmp_path: Path, fake_pyautogui: MagicMock
) -> None:
    """No usable audio (e.g. wake-word listener unavailable) -> the typed/
    manual fallback path via get_instruction()."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(action="unknown", skill_id=None, n_repetitions=1)
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "typed instruction",
    )

    peer.on_wake_word(np.zeros(0, dtype=np.int16))

    nemotron.interpret_text.assert_called_once()
    assert nemotron.interpret_text.call_args.args[0] == "typed instruction"
    assert nemotron.interpret_text.call_args.kwargs.get("screenshot_path") is None


def test_on_wake_word_interpret_failure_does_not_raise(
    tmp_path: Path, fake_pyautogui: MagicMock
) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.side_effect = RuntimeError("network error")
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)

    with patch("heypeer.wakeword.stt.transcribe", return_value="hello"):
        peer.on_wake_word(np.zeros(16000, dtype=np.int16))  # must not raise
