import sys
import threading
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
    """Seeds a skill and enables skill learning — these tests are about the
    skill paths specifically. Learning is off by default in the app itself
    (Hey Peer is voice-to-action only for now); see
    `test_skills_are_not_offered_to_nemotron_by_default`."""
    memory = SkillMemory(tmp_path / "skills.json")
    memory.add(Skill(id="sort_files", name="Sort downloaded files", actions=[]))
    return HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "do it 4 more times",
        learn_skills=True,
    )


def test_skills_are_not_offered_to_nemotron_by_default(tmp_path: Path) -> None:
    """Regression guard: a backlog of learned skills was being sent on every
    request, bloating the prompt with entries like "Repeated sequence in
    unknown app" that could never match a spoken instruction."""
    memory = SkillMemory(tmp_path / "skills.json")
    memory.add(Skill(id="sort_files", name="Sort downloaded files", actions=[]))
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(action="unknown", skill_id=None, n_repetitions=1)
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "do something",
    )

    peer.on_wake_word()

    assert nemotron.interpret_text.call_args.args[1] == []


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
    # Narrated once, before acting. Nothing is spoken afterwards - saying
    # what it's doing already tells the user it happened, so a trailing
    # "C'est fait." was pure repetition.
    assert fake_tts.call_count == 1


def test_successful_file_action_does_not_speak_a_confirmation(tmp_path: Path) -> None:
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
    spoken: list[str] = []
    peer._speak = spoken.append
    peer._speak_async = spoken.append

    peer.on_wake_word()

    assert len(spoken) == 1  # the narration only
    assert "déplace" in spoken[0].lower()


def test_file_action_does_not_wait_for_narration_to_finish(tmp_path: Path) -> None:
    """Regression test: speaking synchronously before acting meant the file
    didn't move until a whole sentence had played - a large part of what the
    user experienced as the action taking too long."""
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

    speaking = threading.Event()
    release = threading.Event()

    def slow_speech(_text: str) -> None:
        speaking.set()
        release.wait(timeout=5)

    peer._speak = slow_speech

    peer.on_wake_word()

    # The move completed even though speech is still playing.
    assert (watched_dir / "Archives" / "facture.pdf").exists()
    assert speaking.is_set()
    release.set()


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
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        learn_skills=True,
        capture_input=True,  # explicitly on: the toggle must still not touch it
    )
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


def test_input_capture_is_off_by_default(tmp_path: Path) -> None:
    """Global mouse/keyboard hooks stay off unless explicitly enabled - they
    were making the user's machine noticeably slow. File-move capture, which
    is cheap and powers the demo skill, must still start."""
    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        watched_dir=watched_dir,
        learn_skills=True,  # the point here is input capture specifically
    )
    peer.watcher.start = MagicMock()
    peer.file_watcher.start = MagicMock()

    peer.start_capture()

    peer.watcher.start.assert_not_called()
    peer.file_watcher.start.assert_called_once()


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
    assert peer._detections.get_nowait() == (fake_audio, False)


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

    # The captured audio starts before the trigger, so the transcript opens
    # with the wake word - which must be verified, then stripped.
    with patch("heypeer.wakeword.stt.transcribe", return_value="Hey Peer, do it again"):
        peer.on_wake_word(audio)

    get_instruction.assert_not_called()
    nemotron.interpret_text.assert_called_once()
    call_args = nemotron.interpret_text.call_args
    assert call_args.args[0] == "do it again"  # wake word stripped
    # No screenshot: this deployment rejects non-string message content with
    # a 400, and the file/folder listing is the grounding that matters.
    assert call_args.kwargs.get("screenshot_path") is None


def test_on_wake_word_ignores_audio_without_the_wake_word(
    tmp_path: Path, fake_pyautogui: MagicMock
) -> None:
    """The always-on detector fires on plenty of ordinary speech (real logs
    showed 0.97-0.99 scores on sentences with no wake word in them). The
    second-stage transcript check must drop those before Nemotron is called
    or anything is executed."""
    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)

    with patch(
        "heypeer.wakeword.stt.transcribe", return_value="déplace le fichier quatre"
    ):
        peer.on_wake_word(np.zeros(16000, dtype=np.int16))

    nemotron.interpret_text.assert_not_called()


def test_on_wake_word_unmutes_after_a_rejected_false_trigger(tmp_path: Path) -> None:
    """A rejected trigger still has to release the listener, or Hey Peer
    would go permanently deaf after the first false positive."""
    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)
    peer._wake_listener = MagicMock()

    with patch("heypeer.wakeword.stt.transcribe", return_value="rien a voir"):
        peer.on_wake_word(np.zeros(16000, dtype=np.int16))

    peer._wake_listener.unmute.assert_called_once()


def test_placeholder_destination_is_not_taken_literally(tmp_path: Path) -> None:
    """Regression test: a truncated instruction made Nemotron answer
    dest_folder="unknown", and Hey Peer created a folder literally named
    "unknown" and moved the file into it."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "4.txt").write_text("x")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="move_file",
        skill_id=None,
        n_repetitions=1,
        src_filename="4.txt",
        dest_folder="unknown",
    )
    peer = _peer_with_watched_dir(tmp_path, nemotron, watched_dir)

    peer.on_wake_word()

    assert not (watched_dir / "unknown").exists()
    assert (watched_dir / "4.txt").exists()


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


def test_undo_reverses_the_last_move(tmp_path: Path) -> None:
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

    nemotron.interpret_text.return_value = Intent(
        action="undo", skill_id=None, n_repetitions=1
    )
    peer.on_wake_word()

    assert (watched_dir / "facture.pdf").exists()
    assert not (watched_dir / "Archives" / "facture.pdf").exists()


def test_undo_with_nothing_to_undo_says_so(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="undo", skill_id=None, n_repetitions=1
    )
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "annule",
    )
    spoken: list[str] = []
    peer._speak = spoken.append

    peer.on_wake_word()  # must not raise

    assert any("rien à annuler" in s for s in spoken)


def test_ask_speaks_the_question_instead_of_failing_silently(tmp_path: Path) -> None:
    """A recognisable-but-incomplete instruction should say what's missing,
    not just "je n'ai pas compris"."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="ask",
        skill_id=None,
        n_repetitions=1,
        question="Vers quel dossier ?",
    )
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "déplace facture",
    )
    spoken: list[str] = []
    peer._speak = spoken.append

    peer.on_wake_word()

    assert spoken == ["Vers quel dossier ?"]


def test_ask_opens_a_followup_window_so_the_answer_needs_no_wake_word(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="ask", skill_id=None, n_repetitions=1, question="Vers quel dossier ?"
    )
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "déplace facture",
    )
    peer._wake_listener = MagicMock()

    peer.on_wake_word()

    peer._wake_listener.arm_followup.assert_called_once()


def test_successful_action_opens_a_followup_window(tmp_path: Path) -> None:
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
    peer._wake_listener = MagicMock()

    peer.on_wake_word()

    peer._wake_listener.arm_followup.assert_called_once()


def test_followup_turn_does_not_require_a_wake_word_in_the_transcript(tmp_path: Path) -> None:
    """A follow-up has no wake word in it by design; checking for one would
    reject every single one."""
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

    with patch("heypeer.wakeword.stt.transcribe", return_value="déplace facture vers Archives"):
        peer.on_wake_word(np.zeros(16000, dtype=np.int16), followup=True)

    assert (watched_dir / "Archives" / "facture.pdf").exists()


def test_non_followup_turn_still_requires_the_wake_word(tmp_path: Path) -> None:
    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)

    with patch("heypeer.wakeword.stt.transcribe", return_value="déplace facture vers Archives"):
        peer.on_wake_word(np.zeros(16000, dtype=np.int16), followup=False)

    nemotron.interpret_text.assert_not_called()


def test_log_survives_characters_the_console_cannot_encode(tmp_path: Path, capsys) -> None:
    """Regression test: Nemotron returned a clarifying question containing a
    non-breaking hyphen, and the UnicodeEncodeError from a cp1252 Windows
    console took down the whole app mid-turn. Some of what reaches `_log` is
    model-generated, so its characters aren't ours to control - a mangled
    character is cosmetic, losing the session over one is not."""
    import io

    nemotron = MagicMock()
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(memory=memory, detector=PatternDetector(), nemotron=nemotron)

    with patch("sys.stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")):
        peer._log("Vers quel dossier veux‑tu le deplacer ?")  # must not raise


def test_configure_console_is_safe_when_streams_cannot_be_reconfigured() -> None:
    """pytest replaces stdout with objects that have no reconfigure()."""
    from heypeer.main import _configure_console

    _configure_console()  # must not raise


def test_asking_a_question_keeps_the_indicator_on_screen(tmp_path: Path) -> None:
    """Regression test: the blob slid off screen the moment a turn ended,
    including right after Hey Peer asked a question - which reads as the
    conversation being over when it is precisely still open."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="ask", skill_id=None, n_repetitions=1, question="Vers quel dossier ?"
    )
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "deplace facture",
    )
    peer.debug_window = MagicMock()
    peer._wake_listener = MagicMock()
    peer._speak = lambda _text: None

    peer.on_wake_word()

    states = [c.args[0] for c in peer.debug_window.set_state.call_args_list]
    assert states[-1] == "awaiting"
    assert "listening" not in states[states.index("awaiting"):]


def test_a_turn_with_no_followup_hides_the_indicator(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="unknown", skill_id=None, n_repetitions=1
    )
    memory = SkillMemory(tmp_path / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=nemotron,
        get_instruction=lambda: "quelque chose",
    )
    peer.debug_window = MagicMock()
    peer._speak = lambda _text: None

    peer.on_wake_word()

    assert [c.args[0] for c in peer.debug_window.set_state.call_args_list][-1] == "listening"
