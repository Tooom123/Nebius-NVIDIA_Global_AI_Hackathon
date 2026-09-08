import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from heypeer.main import _SHUTDOWN, HeyPeer
from heypeer.nemotron.intent import Intent


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
    return HeyPeer(nemotron=nemotron, get_instruction=lambda: "do it 4 more times")


def _capture_speech(target: list) -> "Callable[..., None]":
    """A `peer._speak`/`_speak_async` replacement that records what was
    said, for tests that only care about the text - not `list.append`
    directly, since `_speak` now also takes a `language` keyword argument
    that a bare `list.append` cannot accept."""
    def capture(text: str, language: str = "fr") -> None:
        target.append(text)
    return capture


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
    peer._speak = _capture_speech(spoken)
    peer._speak_async = _capture_speech(spoken)

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

    def slow_speech(_text: str, language: str = "fr") -> None:
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



def _peer_with_watched_dir(tmp_path: Path, nemotron: MagicMock, watched_dir: Path) -> HeyPeer:
    return HeyPeer(
        nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "instruction"
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




def test_on_wake_detected_only_enqueues_does_not_call_get_instruction(tmp_path: Path) -> None:
    """Regression test: the wake-word audio thread's on_detected callback
    must stay cheap and non-blocking. Handling the instruction inline (i.e.
    calling get_instruction()/input() from that thread) was found to not
    actually wait for keyboard input on Windows."""
    nemotron = MagicMock()
    get_instruction = MagicMock(return_value="do it 4 more times")
    peer = HeyPeer(
        nemotron=nemotron,
        get_instruction=get_instruction,
    )

    fake_audio = MagicMock()
    peer._on_wake_detected(fake_audio)

    get_instruction.assert_not_called()
    assert peer._detections.get_nowait() == (fake_audio, False)


def test_on_quit_enqueues_shutdown_sentinel(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = HeyPeer(nemotron=nemotron)

    peer._on_quit()

    assert peer._detections.get_nowait() is _SHUTDOWN


def test_on_wake_detected_mutes_the_listener_immediately(tmp_path: Path) -> None:
    """Regression test: real logs showed the audio thread picking up a
    second "Hey Peer" (or ambient chatter) while the first instruction was
    still being transcribed/interpreted - muting now starts the instant a
    detection comes in, not just around the later TTS-playback window."""
    nemotron = MagicMock()
    peer = HeyPeer(nemotron=nemotron)
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
    peer = HeyPeer(
        nemotron=nemotron,
        get_instruction=lambda: "typed instruction",
    )
    peer._wake_listener = MagicMock()

    peer.on_wake_word()

    peer._wake_listener.unmute.assert_called_once()


def test_on_wake_word_unmutes_even_if_interpretation_fails(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.side_effect = RuntimeError("network error")
    peer = HeyPeer(
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
        action="unknown", skill_id=None, n_repetitions=1
    )
    get_instruction = MagicMock(return_value="should not be called")
    peer = HeyPeer(
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
    peer = HeyPeer(nemotron=nemotron)

    with patch(
        "heypeer.wakeword.stt.transcribe", return_value="déplace le fichier quatre"
    ):
        peer.on_wake_word(np.zeros(16000, dtype=np.int16))

    nemotron.interpret_text.assert_not_called()


def test_on_wake_word_unmutes_after_a_rejected_false_trigger(tmp_path: Path) -> None:
    """A rejected trigger still has to release the listener, or Hey Peer
    would go permanently deaf after the first false positive."""
    nemotron = MagicMock()
    peer = HeyPeer(nemotron=nemotron)
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
    peer = HeyPeer(
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
    peer = HeyPeer(nemotron=nemotron)

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
    peer = HeyPeer(
        nemotron=nemotron,
        get_instruction=lambda: "annule",
    )
    spoken: list[str] = []
    peer._speak = _capture_speech(spoken)

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
    peer = HeyPeer(
        nemotron=nemotron,
        get_instruction=lambda: "déplace facture",
    )
    spoken: list[str] = []
    peer._speak = _capture_speech(spoken)

    peer.on_wake_word()

    assert spoken == ["Vers quel dossier ?"]


def test_ask_opens_a_followup_window_so_the_answer_needs_no_wake_word(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="ask", skill_id=None, n_repetitions=1, question="Vers quel dossier ?"
    )
    peer = HeyPeer(
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
    peer = HeyPeer(nemotron=nemotron)

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
    peer = HeyPeer(nemotron=nemotron)

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
    peer = HeyPeer(
        nemotron=nemotron,
        get_instruction=lambda: "deplace facture",
    )
    peer.debug_window = MagicMock()
    peer._wake_listener = MagicMock()
    peer._speak = lambda _text, language="fr": None

    peer.on_wake_word()

    states = [c.args[0] for c in peer.debug_window.set_state.call_args_list]
    assert states[-1] == "awaiting"
    assert "listening" not in states[states.index("awaiting"):]


def test_a_turn_with_no_followup_hides_the_indicator(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="unknown", skill_id=None, n_repetitions=1
    )
    peer = HeyPeer(
        nemotron=nemotron,
        get_instruction=lambda: "quelque chose",
    )
    peer.debug_window = MagicMock()
    peer._speak = lambda _text, language="fr": None

    peer.on_wake_word()

    assert [c.args[0] for c in peer.debug_window.set_state.call_args_list][-1] == "listening"


def test_wake_listener_is_wired_to_callbacks_that_exist(tmp_path: Path) -> None:
    """Regression test for a crash that reached the user: `_run_wake_listener`
    passed `on_ready=self._on_ready_to_listen` while that method did not
    exist, so the listener thread died with an AttributeError the first time
    voice started.

    Nothing covered this because every other test calls `on_wake_word`
    directly and never goes through `_run_wake_listener`, which needs a real
    WakeWordListener. The wiring between the two was simply untested - and it
    is exactly the kind of thing that only fails on a real machine, in a
    background thread, at the worst moment."""
    nemotron = MagicMock()
    peer = HeyPeer(nemotron=nemotron)
    fake_listener = MagicMock()

    with (
        patch("heypeer.wakeword.listener.WakeWordListener", return_value=fake_listener),
        patch("heypeer.wakeword.listener.default_model_path") as model_path,
    ):
        model_path.return_value = tmp_path / "model.onnx"
        (tmp_path / "model.onnx").write_bytes(b"x")
        peer._run_wake_listener()

    fake_listener.start.assert_called_once()
    for name, callback in fake_listener.start.call_args.kwargs.items():
        if name.startswith("on_"):
            assert callable(callback), f"{name} is not callable"


def test_wake_listener_failure_does_not_raise(tmp_path: Path) -> None:
    """A missing model or a bad audio device degrades to a message rather
    than an unhandled traceback in a background thread."""
    peer = HeyPeer(nemotron=MagicMock())

    with patch("heypeer.wakeword.listener.default_model_path") as model_path:
        model_path.return_value = tmp_path / "absent.onnx"
        peer._run_wake_listener()  # must not raise

    assert peer._wake_ready.is_set()
    assert peer._wake_listener is None


# --- Conversation ---------------------------------------------------------
#
# Hey Peer used to answer exactly one kind of turn: a file command. Anything
# else fell through to "je n'ai pas compris" and the exchange ended there.
# These cover the other half - that an ordinary spoken turn gets an ordinary
# spoken answer, and that an exchange lasts until it is actually finished
# rather than ending after every single sentence.


def _conversational(peer: HeyPeer) -> list:
    """Silences speech and gives the peer a listener to arm, returning what
    it says. Speaking for real would load a Piper voice per test."""
    said: list = []
    peer._speak = _capture_speech(said)
    peer._wake_listener = MagicMock()
    return said


def test_a_question_that_is_not_a_command_gets_a_spoken_answer(tmp_path: Path) -> None:
    """"Comment ca va ?" is not a file operation and must not be forced into
    one. It is answered, and nothing on disk is touched."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply",
        skill_id=None,
        n_repetitions=1,
        speech="Tres bien, et toi ?",
        end_turn=False,
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=tmp_path, get_instruction=lambda: "comment ca va")
    said = _conversational(peer)

    peer.on_wake_word()

    assert said == ["Tres bien, et toi ?"]
    assert list(tmp_path.iterdir()) == []


def test_an_open_exchange_keeps_listening_without_a_wake_word(tmp_path: Path) -> None:
    """The point of the whole thing: the user answers back by just talking.
    `end_turn` False has to open the follow-up window, or the reply is lost."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1, speech="Et toi ?", end_turn=False
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "salut")
    _conversational(peer)

    peer.on_wake_word()

    peer._wake_listener.arm_followup.assert_called_once()
    peer._wake_listener.cancel_followup.assert_not_called()


def test_a_finished_exchange_stops_listening_and_is_forgotten(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1, speech="De rien !", end_turn=True
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "merci")
    _conversational(peer)

    peer.on_wake_word()

    peer._wake_listener.arm_followup.assert_not_called()
    peer._wake_listener.cancel_followup.assert_called()
    assert peer._history == []


def test_the_next_turn_sees_what_was_already_said(tmp_path: Path) -> None:
    """Without this an exchange is a series of unrelated commands: "et dans
    Archives du coup ?" is uninterpretable with no memory of the question it
    answers."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="ask", skill_id=None, n_repetitions=1, question="Vers quel dossier ?"
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "deplace facture")
    _conversational(peer)

    peer.on_wake_word()
    peer.on_wake_word()

    history = nemotron.interpret_text.call_args_list[1].kwargs["history"]
    assert {"role": "user", "content": "deplace facture"} in history
    assert {"role": "assistant", "content": "Vers quel dossier ?"} in history
    # The first turn had nothing to go on.
    assert nemotron.interpret_text.call_args_list[0].kwargs["history"] == []


def test_a_new_exchange_does_not_inherit_the_previous_one(tmp_path: Path) -> None:
    """Carrying an old conversation into the next "Hey Peer" would have Hey
    Peer answering a question nobody just asked."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1, speech="Bien sur.", end_turn=True
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "salut")
    _conversational(peer)

    peer.on_wake_word()
    peer.on_wake_word()

    assert nemotron.interpret_text.call_args_list[1].kwargs["history"] == []


def test_ask_holds_the_exchange_open_even_if_the_model_says_otherwise(tmp_path: Path) -> None:
    """A question with `end_turn` true is self-contradictory - Hey Peer would
    ask the user something and stop listening for the answer in the same
    breath. The structure of the action wins over the flag."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="ask",
        skill_id=None,
        n_repetitions=1,
        question="Vers quel dossier ?",
        end_turn=True,
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "deplace facture")
    _conversational(peer)

    peer.on_wake_word()

    peer._wake_listener.arm_followup.assert_called_once()


def test_the_history_is_bounded(tmp_path: Path) -> None:
    """A long exchange must not grow the prompt without limit."""
    from heypeer.main import HISTORY_TURNS

    peer = HeyPeer(nemotron=MagicMock())
    for i in range(HISTORY_TURNS * 3):
        peer._remember(f"question {i}", f"answer {i}")

    assert len(peer._history) == HISTORY_TURNS * 2
    assert peer._history[-1]["content"] == f"answer {HISTORY_TURNS * 3 - 1}"


def test_a_file_action_is_narrated_in_the_models_own_words(tmp_path: Path) -> None:
    """The fixed narration reads like a template being filled in. When
    Nemotron phrases the sentence for the actual request, use that - falling
    back to the template only when it doesn't."""
    watched = tmp_path / "Downloads"
    watched.mkdir()
    (watched / "facture.pdf").write_text("x")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="move_file",
        skill_id=None,
        n_repetitions=1,
        src_filename="facture.pdf",
        dest_folder="Archives",
        speech="C'est parti, je range la facture.",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched, get_instruction=lambda: "range la facture")
    said = _conversational(peer)
    peer._speak_async = _capture_speech(said)

    peer.on_wake_word()

    assert said == ["C'est parti, je range la facture."]
    assert (watched / "Archives" / "facture.pdf").is_file()


# --- Activation timing ----------------------------------------------------
#
# The order the user asked for, and had to ask for twice: "Hey Peer" -> the
# blob comes down -> the beep says it is listening -> the instruction. Each
# step here failed on real hardware in a way no test could see, because both
# the blob's arrival and the model's readiness live outside this process.


def test_the_chime_waits_for_the_blob_to_be_on_screen(tmp_path: Path) -> None:
    """The beep announces that Hey Peer is listening, so it must land after
    the blob, not during its slide.

    It used to be scheduled off the slide's nominal duration, which ignored
    the time the overlay process takes to wake up and start sliding at all -
    so the beep regularly played while the blob was still on its way down,
    which is what the user reported hearing.
    """
    order: list[str] = []
    peer = HeyPeer(nemotron=MagicMock())
    peer.debug_window = MagicMock()
    peer.debug_window.wait_until_visible.side_effect = lambda _t: order.append("blob landed") or True

    with patch(
        "heypeer.wakeword.listener.play_activation_chime",
        side_effect=lambda blocking=False: order.append(f"chime(blocking={blocking})"),
    ):
        peer._on_ready_to_listen()

    assert order == ["blob landed", "chime(blocking=True)"]


def test_a_stalled_indicator_does_not_cost_the_user_their_turn(tmp_path: Path) -> None:
    """If the overlay never reports landing, chime anyway. A UI that has gone
    quiet must degrade to a missing visual, not to Hey Peer refusing to
    listen."""
    peer = HeyPeer(nemotron=MagicMock())
    peer.debug_window = MagicMock()
    peer.debug_window.wait_until_visible.return_value = False
    chime = MagicMock()

    with patch("heypeer.wakeword.listener.play_activation_chime", chime):
        peer._on_ready_to_listen()

    chime.assert_called_once_with(blocking=True)


def test_verification_is_skipped_rather_than_blocking_on_a_cold_model(tmp_path: Path) -> None:
    """Regression test for the first "Hey Peer" after startup being missed.

    Verification runs on the microphone thread. Whisper's verification model
    is still loading in the background for the first several seconds, and
    asking a cold model to transcribe there did not merely add latency: it
    stopped the mic being read for the whole load, so Hey Peer was deaf
    exactly when the user was speaking to it. The activation was not lost, it
    was answered long after they had given up and repeated themselves.
    """
    peer = HeyPeer(nemotron=MagicMock())
    peer.debug_window = MagicMock()
    transcribe = MagicMock()

    with (
        patch("heypeer.wakeword.stt.is_loaded", return_value=False),
        patch("heypeer.wakeword.stt.transcribe", transcribe),
    ):
        accepted = peer._verify_wake_word(np.zeros(32000, dtype=np.int16))

    assert accepted is True
    transcribe.assert_not_called()
    peer.debug_window.set_state.assert_called_with("recording")


def test_verification_runs_normally_once_the_model_is_warm(tmp_path: Path) -> None:
    peer = HeyPeer(nemotron=MagicMock())
    peer.debug_window = MagicMock()

    with (
        patch("heypeer.wakeword.stt.is_loaded", return_value=True),
        patch("heypeer.wakeword.stt.transcribe", return_value="une phrase ordinaire"),
    ):
        accepted = peer._verify_wake_word(np.zeros(32000, dtype=np.int16))

    assert accepted is False  # no wake word in it


# --- Applications and music ----------------------------------------------
#
# The first thing Hey Peer does that is not about files. What matters here is
# the boundary: a name it does not recognise must never reach the OS, and it
# must never announce music that is not playing.


def test_an_unknown_application_is_refused_rather_than_launched(tmp_path: Path) -> None:
    """Everything on this path started as a speech transcript and then passed
    through a language model. "Run whatever it said" is not an option."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="open_app", skill_id=None, n_repetitions=1,
        target_name="Machin", speech="J'ouvre Machin.",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "ouvre Machin")
    said = _conversational(peer)

    with patch("heypeer.executor.apps.launch") as launch:
        peer.on_wake_word()

    launch.assert_not_called()
    assert said == ["Je ne connais pas l'application Machin."]


def test_launching_spotify_starts_the_music_too(tmp_path: Path) -> None:
    """"Lance Spotify" means start it and play. Plain `launch` would open the
    app and leave the user in silence."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="open_app", skill_id=None, n_repetitions=1,
        target_name="spotify", speech="Je lance Spotify.",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "lance spotify")
    _conversational(peer)
    peer._speak_async = MagicMock()

    with patch("heypeer.executor.spotify.launch_and_play") as launch_and_play:
        peer.on_wake_word()

    launch_and_play.assert_called_once()


def test_an_ordinary_app_is_just_launched(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="open_app", skill_id=None, n_repetitions=1, target_name="Chrome",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "ouvre Chrome")
    _conversational(peer)
    peer._speak_async = MagicMock()

    with patch("heypeer.executor.apps.launch") as launch:
        peer.on_wake_word()

    assert launch.call_args.args[0].name == "Chrome"


def test_a_resolved_track_is_played_and_named(tmp_path: Path) -> None:
    """Saying what was actually found is how the user discovers the search
    matched something other than what they asked for."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="play_music", skill_id=None, n_repetitions=1,
        query="Alright Kendrick Lamar",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "mets Alright de Kendrick Lamar")
    _conversational(peer)
    narrated: list = []
    peer._speak_async = _capture_speech(narrated)

    from heypeer.executor.spotify import Track

    with (
        patch("heypeer.executor.spotify.credentials_missing", return_value=False),
        patch(
            "heypeer.executor.spotify.find_track",
            return_value=Track("spotify:track:abc", "Starman", "David Bowie"),
        ),
        patch("heypeer.executor.spotify.play_track") as play_track,
    ):
        peer.on_wake_word()

    # play_track, not play_uri: it applies the cold-start-only "press play"
    # fix (test_spotify.py covers that logic on its own), and patching it
    # here rather than play_uri also keeps this test from paying its real
    # settle-time sleep.
    play_track.assert_called_once_with("spotify:track:abc")
    assert narrated == ["Je lance Starman par David Bowie."]


def test_the_track_name_comes_from_the_search_not_from_the_model(tmp_path: Path) -> None:
    """The model writes its sentence before anything has been looked up, so
    it can only repeat what the user said. Naming the resolved track is how
    they find out the search matched something else."""
    from heypeer.executor.spotify import Track

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="play_music", skill_id=None, n_repetitions=1, query="starman bowie",
        speech="Je mets starman.",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "mets starman de bowie")
    _conversational(peer)
    narrated: list = []
    peer._speak_async = _capture_speech(narrated)

    with (
        patch("heypeer.executor.spotify.credentials_missing", return_value=False),
        patch("heypeer.executor.spotify.find_track",
              return_value=Track("spotify:track:abc", "Starman", "David Bowie")),
        patch("heypeer.executor.spotify.play_track"),
    ):
        peer.on_wake_word()

    assert narrated == ["Je lance Starman par David Bowie."]


def test_without_credentials_it_opens_the_search_and_says_so(tmp_path: Path) -> None:
    """The state the user is in until they register a Spotify app. Opening
    the search is not playing the track, so claiming to have started the
    music would be a lie the user hears immediately - silence.

    `credentials_missing` is mocked rather than relied on to fall out of an
    empty environment: this test is about the app's behaviour when
    unconfigured, not about what happens to be in the developer's own
    `.env` at the moment it runs - which, once real Spotify credentials
    exist there, would silently flip this test into exercising the wrong
    branch.
    """
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="play_music", skill_id=None, n_repetitions=1, query="Alright Kendrick Lamar",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "mets Alright")
    _conversational(peer)
    narrated: list = []
    peer._speak_async = _capture_speech(narrated)

    with (
        patch("heypeer.executor.spotify.credentials_missing", return_value=True),
        patch("heypeer.executor.spotify.find_track") as find_track,
        patch("heypeer.executor.spotify.play_uri") as play_uri,
    ):
        peer.on_wake_word()

    find_track.assert_not_called()  # nothing to search with
    assert play_uri.call_args.args[0].startswith("spotify:search:")
    assert "configuration Spotify" in narrated[0]
    assert "pas trouve" not in narrated[0]  # not a failed search - a missing setup step


def _armed_a_followup(peer) -> bool:
    """Whether the turn left the microphone open for a reply.

    `on_wake_word` closes the exchange and hides the blob for any turn that
    armed nothing, so this is the same question as "did the turn end".
    """
    return peer._wake_listener.arm_followup.called


def test_launching_an_app_ends_the_turn(tmp_path: Path) -> None:
    """Reported from real use: after "lance Spotify" the blob stayed on
    screen and Hey Peer kept listening - over the music it had just started,
    which through a headset it then heard as speech. Opening an app finishes
    the request."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="open_app", skill_id=None, n_repetitions=1, target_name="spotify",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "lance spotify")
    _conversational(peer)
    peer._speak_async = MagicMock()

    with patch("heypeer.executor.spotify.launch_and_play"):
        peer.on_wake_word()

    assert not _armed_a_followup(peer)


def test_starting_music_ends_the_turn(tmp_path: Path) -> None:
    """Same reason, more sharply: holding the microphone open after starting
    playback means holding it open over the music."""
    from heypeer.executor.spotify import Track

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="play_music", skill_id=None, n_repetitions=1, query="starman bowie",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "mets starman")
    _conversational(peer)
    peer._speak_async = MagicMock()

    with (
        patch("heypeer.executor.spotify.credentials_missing", return_value=False),
        patch("heypeer.executor.spotify.find_track",
              return_value=Track("spotify:track:abc", "Starman", "David Bowie")),
        patch("heypeer.executor.spotify.play_track"),
    ):
        peer.on_wake_word()

    assert not _armed_a_followup(peer)


def test_an_unknown_app_keeps_the_exchange_open(tmp_path: Path) -> None:
    """The one case on this path that is *not* the end of the request: Hey
    Peer just said it doesn't know that app, so a rephrasing is expected."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="open_app", skill_id=None, n_repetitions=1, target_name="Machin",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "ouvre Machin")
    _conversational(peer)

    peer.on_wake_word()

    assert _armed_a_followup(peer)


def test_a_web_search_opens_a_quoted_search_url(tmp_path: Path) -> None:
    """The query is encoded into a fixed search URL rather than the model
    being asked for an address: a search string can say anything, a URL can
    *go* anywhere."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="search_web", skill_id=None, n_repetitions=1,
        query="meteo demain Paris", speech="Je cherche la meteo.",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "cherche la meteo de demain")
    _conversational(peer)
    peer._speak_async = MagicMock()

    with patch("heypeer.executor.apps.open_url") as open_url:
        peer.on_wake_word()

    url = open_url.call_args.args[0]
    assert url.startswith("https://www.google.com/search?q=")
    assert " " not in url
    assert not _armed_a_followup(peer)


# --- Action-registration coverage (round 32) -------------------------------
#
# The other half of "the prompt says both yes and no": *this* code, not the
# prompt text, forgetting to wire a newly added action into dispatch. Found
# while adding this check: intent.action == "ask" was a dead elif branch here
# for as long as SPOKEN_ACTIONS has existed - the earlier `if intent.action
# in SPOKEN_ACTIONS:` block already returns for "ask" before the elif chain
# is ever reached, so it silently used a different fallback message and a
# different follow-up window than the one every test actually exercised.
# Removed, and this test is what would have caught it: not "does ask work"
# (existing tests already covered that, on the branch that actually runs),
# but "is every action's string literal referenced somewhere in this
# method" - which a dead, unreachable elif still technically satisfies, so
# it does not catch that specific class of staleness. It does catch the
# more common one: an action added to ACTIONS with no branch for it at all.


def test_every_action_has_a_branch_in_dispatch() -> None:
    """Static, not behavioural: parses `_dispatch_intent`'s own source and
    checks every `ACTIONS` member (other than the ones handled generically
    via `SPOKEN_ACTIONS`, and "unknown", which has no dedicated branch by
    design - it falls through to the final `else`) appears as a compared
    string literal somewhere in the method.

    This is deliberately cheap and mechanical rather than a battery of live
    per-action tests: it exists to catch a *forgotten* branch the moment an
    action is added to `ACTIONS`, not to verify each branch's behaviour -
    the tests elsewhere in this file already do that per action.
    """
    import ast
    import inspect
    import textwrap

    from heypeer.nemotron.intent import ACTIONS, SPOKEN_ACTIONS

    source = textwrap.dedent(inspect.getsource(HeyPeer._dispatch_intent))
    tree = ast.parse(source)
    compared_literals = {
        node.comparators[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.comparators[0], ast.Constant)
        and isinstance(node.comparators[0].value, str)
    }

    for action in ACTIONS:
        if action in SPOKEN_ACTIONS or action == "unknown":
            continue
        assert action in compared_literals, (
            f"{action!r} is in ACTIONS but _dispatch_intent has no branch for it"
        )


def test_dispatch_has_no_branch_for_an_action_that_does_not_exist() -> None:
    """The other direction: a branch for a retired or misspelled action name
    would be silently unreachable, the same way the "ask" elif was. Every
    action-shaped string literal compared in `_dispatch_intent` should name
    something `ACTIONS` still recognises."""
    import ast
    import inspect
    import textwrap

    from heypeer.nemotron.intent import ACTIONS

    source = textwrap.dedent(inspect.getsource(HeyPeer._dispatch_intent))
    tree = ast.parse(source)
    compared_literals = {
        node.comparators[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.comparators[0], ast.Constant)
        and isinstance(node.comparators[0].value, str)
    }

    for literal in compared_literals:
        assert literal in ACTIONS, (
            f"_dispatch_intent compares against {literal!r}, which is not in ACTIONS"
        )


# --- Fast path integration (round 32) --------------------------------------
#
# heypeer/nemotron/fast_path.py handles a small, closed vocabulary of file
# commands without a network round trip. These tests are about the wiring -
# does it actually short-circuit Nemotron when it should, and never touch it
# when it shouldn't - not the matching logic itself, which test_fast_path.py
# already covers on its own.


def test_a_matching_instruction_never_reaches_nemotron(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")
    nemotron = MagicMock()
    peer = HeyPeer(
        nemotron=nemotron, watched_dir=watched_dir,
        get_instruction=lambda: "supprime facture.pdf",
    )

    with patch("send2trash.send2trash") as trash:
        peer.on_wake_word()

    nemotron.interpret_text.assert_not_called()
    trash.assert_called_once_with(str(watched_dir / "facture.pdf"))


def test_a_non_matching_instruction_still_goes_to_nemotron(tmp_path: Path) -> None:
    """The overwhelming majority of instructions - anything outside the
    three fixed shapes fast_path recognises - must be entirely unaffected by
    its existence."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1, speech="Tres bien, et toi ?",
    )
    peer = HeyPeer(
        nemotron=nemotron, watched_dir=watched_dir,
        get_instruction=lambda: "comment ca va",
    )

    peer.on_wake_word()

    nemotron.interpret_text.assert_called_once()


def test_an_unresolvable_fast_path_candidate_falls_back_to_nemotron(tmp_path: Path) -> None:
    """Shaped exactly like a fast-path command, but the file doesn't exist -
    fast_path declines, and the instruction must still reach the model
    rather than silently going nowhere."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1,
        speech="Je ne trouve pas ce fichier.",
    )
    peer = HeyPeer(
        nemotron=nemotron, watched_dir=watched_dir,
        get_instruction=lambda: "supprime introuvable.pdf",
    )

    peer.on_wake_word()

    nemotron.interpret_text.assert_called_once()


def test_the_fast_path_is_skipped_during_an_open_exchange(tmp_path: Path) -> None:
    """Even text shaped exactly like a fast-path command must go through
    Nemotron once a conversation is already open - a fixed sentence shape
    cannot know whether "supprime facture.pdf" here actually continues
    whatever the open exchange was about."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="delete_file", skill_id=None, n_repetitions=1, src_filename="facture.pdf",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir)
    peer._history.append({"role": "user", "content": "some earlier turn"})

    with patch("send2trash.send2trash"):
        peer._interpret("supprime facture.pdf")

    nemotron.interpret_text.assert_called_once()


def test_the_fast_path_also_applies_to_the_manual_prompt_path(tmp_path: Path) -> None:
    """`_handle_instruction` is the tray/manual-prompt entry point - a
    separate call site from the voice path, and easy to leave unwired by
    accident."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")
    nemotron = MagicMock()
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir)

    with patch("send2trash.send2trash") as trash:
        peer._handle_instruction("supprime facture.pdf")

    nemotron.interpret_text.assert_not_called()
    trash.assert_called_once_with(str(watched_dir / "facture.pdf"))


# --- Language matching (round 34) ------------------------------------------
#
# "des fois je parle an anglais, le resultat est bon mais la parole qui
# confirme est en francais donc pas de logique sur la reponse" - the action
# taken was correct, but Hey Peer answered in French regardless of what
# language the instruction was actually in. Nemotron now reports which
# language it wrote in (`intent.language`); these tests are about the wiring
# from that field to the voice `tts.speak` actually uses - the routing logic
# for the field itself lives in the live-verified system prompt, not here.


def test_an_english_reply_is_spoken_in_english(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1,
        speech="I'm doing well, thanks.", language="en",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "how are you?")

    peer.on_wake_word()

    fake_tts.assert_called_once_with("I'm doing well, thanks.", language="en")


def test_a_french_reply_is_spoken_in_french(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1,
        speech="Tres bien, et toi ?", language="fr",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "comment ca va ?")

    peer.on_wake_word()

    fake_tts.assert_called_once_with("Tres bien, et toi ?", language="fr")


def test_an_intent_with_no_language_reported_defaults_to_french(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """An older mock, a malformed answer, or the fast path (which is French-
    only by construction and never sets this field) must not go silent or
    crash - French is the existing, safe default."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1, speech="Tres bien.",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "comment ca va ?")

    peer.on_wake_word()

    fake_tts.assert_called_once_with("Tres bien.", language="fr")


def test_an_english_file_action_is_narrated_in_english(tmp_path: Path, fake_tts: MagicMock) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="delete_file", skill_id=None, n_repetitions=1,
        src_filename="facture.pdf", speech="Deleting facture.pdf.", language="en",
    )
    peer = HeyPeer(
        nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "delete facture.pdf",
    )

    with patch("send2trash.send2trash"):
        peer.on_wake_word()

    fake_tts.assert_called_once_with("Deleting facture.pdf.", language="en")


def test_an_unknown_app_in_english_declines_in_english(tmp_path: Path, fake_tts: MagicMock) -> None:
    """Hey Peer's own fixed fallback strings, not just Nemotron's text, must
    also match - answering "Machin" in French after being asked in English
    is exactly the inconsistency that was reported."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="open_app", skill_id=None, n_repetitions=1,
        target_name="Machin", language="en",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "open Machin")

    peer.on_wake_word()

    fake_tts.assert_called_once_with("I don't know the application Machin.", language="en")


def test_a_music_track_is_named_with_by_not_par_in_english(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    from heypeer.executor.spotify import Track

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="play_music", skill_id=None, n_repetitions=1,
        query="starman bowie", language="en",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "play starman by bowie")

    with (
        patch("heypeer.executor.spotify.credentials_missing", return_value=False),
        patch("heypeer.executor.spotify.find_track",
              return_value=Track("spotify:track:abc", "Starman", "David Bowie")),
        patch("heypeer.executor.spotify.play_track"),
    ):
        peer.on_wake_word()

    fake_tts.assert_called_once_with("Playing Starman by David Bowie.", language="en")


# --- System control and clipboard (round 35) --------------------------------
#
# Volume, brightness, window control, and the clipboard - the wiring from a
# dispatched Intent to executor/system.py and executor/clipboard.py.
# Everything Windows-specific inside those modules is already covered on its
# own (tests/test_system.py, tests/test_clipboard.py); these are about
# main.py's own logic: which function gets called for which target, and
# what gets said when it does or doesn't work.


def test_adjust_volume_mute_calls_the_toggle(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="adjust_volume", skill_id=None, n_repetitions=1, target_name="mute",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "coupe le son")

    with patch("heypeer.executor.system.volume_mute_toggle") as toggle:
        peer.on_wake_word()

    toggle.assert_called_once()


def test_adjust_volume_up_calls_volume_up(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="adjust_volume", skill_id=None, n_repetitions=1, target_name="up",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "monte le son")

    with patch("heypeer.executor.system.volume_up") as up:
        peer.on_wake_word()

    up.assert_called_once()


def test_adjust_brightness_success_is_narrated(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="adjust_brightness", skill_id=None, n_repetitions=1, target_name="up",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "monte la luminosite")

    with patch("heypeer.executor.system.adjust_brightness", return_value=True):
        peer.on_wake_word()

    fake_tts.assert_called_once_with("Je monte la luminosité.", language="fr")


def test_adjust_brightness_failure_is_reported_honestly(tmp_path: Path, fake_tts: MagicMock) -> None:
    """The one action here that can genuinely fail on correctly-working
    hardware (an external monitor) - must say so, not claim success."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="adjust_brightness", skill_id=None, n_repetitions=1, target_name="down",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "baisse la luminosite")

    with patch("heypeer.executor.system.adjust_brightness", return_value=False):
        peer.on_wake_word()

    fake_tts.assert_called_once_with(
        "Je ne peux pas régler la luminosité sur cet écran.", language="fr"
    )


def test_maximize_window_success_is_narrated(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="maximize_window", skill_id=None, n_repetitions=1, target_name="Chrome",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "mets Chrome en plein ecran")

    with patch("heypeer.executor.system.maximize_window", return_value=True) as maximize:
        peer.on_wake_word()

    maximize.assert_called_once_with("Chrome")
    fake_tts.assert_called_once_with("Je mets Chrome en plein écran.", language="fr")


def test_close_window_not_found_declines_honestly(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="close_window", skill_id=None, n_repetitions=1, target_name="Chrome",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "ferme Chrome")

    with patch("heypeer.executor.system.close_window", return_value=False):
        peer.on_wake_word()

    fake_tts.assert_called_once_with(
        "Je ne vois pas de fenêtre ouverte pour Chrome.", language="fr"
    )


def test_minimize_all_calls_the_executor(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="minimize_all", skill_id=None, n_repetitions=1,
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "montre le bureau")

    with patch("heypeer.executor.system.minimize_all") as minimize_all:
        peer.on_wake_word()

    minimize_all.assert_called_once()


def test_clipboard_copy_sends_the_shortcut(tmp_path: Path) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="clipboard_copy", skill_id=None, n_repetitions=1,
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "copie ca")

    with patch("heypeer.executor.clipboard.copy_selection") as copy_selection:
        peer.on_wake_word()

    copy_selection.assert_called_once()


def test_clipboard_read_speaks_the_intro_then_the_summary(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """Two spoken parts: the intro Nemotron wrote before the clipboard was
    available to it, then the actual content, summarized after it's read -
    see _run_clipboard_read's docstring for why this can't be a single
    "speech" field the classifier fills in."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="clipboard_read", skill_id=None, n_repetitions=1,
        speech="Voici ce qu'il y a dans le presse-papier :",
    )
    nemotron.summarize_for_speech.return_value = "Une facture de 42 euros."
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "qu'est-ce qu'il y a dans mon presse-papier")

    with patch("heypeer.executor.clipboard.read", return_value="Facture #1, 42 EUR"):
        peer.on_wake_word()

    assert fake_tts.call_args_list[0].args == ("Voici ce qu'il y a dans le presse-papier :",)
    assert fake_tts.call_args_list[1].args == ("Une facture de 42 euros.",)
    nemotron.summarize_for_speech.assert_called_once_with("Facture #1, 42 EUR", "fr")


def test_clipboard_read_on_an_empty_clipboard_says_so(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="clipboard_read", skill_id=None, n_repetitions=1,
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "lis mon presse-papier")

    with patch("heypeer.executor.clipboard.read", return_value=None):
        peer.on_wake_word()

    fake_tts.assert_called_once_with("Le presse-papier est vide.", language="fr")
    nemotron.summarize_for_speech.assert_not_called()


def test_clipboard_read_summarization_failure_is_reported(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="clipboard_read", skill_id=None, n_repetitions=1, speech="Voici :",
    )
    nemotron.summarize_for_speech.side_effect = Exception("network down")
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "lis mon presse-papier")

    with patch("heypeer.executor.clipboard.read", return_value="some text"):
        peer.on_wake_word()

    assert fake_tts.call_args_list[-1].args == ("Je n'ai pas réussi à lire le presse-papier.",)


def test_none_of_the_new_system_actions_open_a_followup_window(tmp_path: Path) -> None:
    """One-shot actions, same as opening an app or playing music - holding
    the microphone open afterwards is not what any of these need."""
    for action, target_name in [
        ("adjust_volume", "up"), ("maximize_window", "Chrome"), ("minimize_all", None),
        ("clipboard_copy", None),
    ]:
        nemotron = MagicMock()
        nemotron.interpret_text.return_value = Intent(
            action=action, skill_id=None, n_repetitions=1, target_name=target_name,
        )
        peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "instruction")
        peer._wake_listener = MagicMock()

        with (
            patch("heypeer.executor.system.volume_up"),
            patch("heypeer.executor.system.maximize_window", return_value=True),
            patch("heypeer.executor.system.minimize_all"),
            patch("heypeer.executor.clipboard.copy_selection"),
        ):
            peer.on_wake_word()

        assert not peer._wake_listener.arm_followup.called, f"{action} armed a followup"


# --- Documents and screen (round 36) ----------------------------------------


def test_summarize_document_reads_extracts_and_summarizes(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="summarize_document", skill_id=None, n_repetitions=1,
        target_name="facture.pdf", speech="Voici un résumé de facture.pdf :",
    )
    nemotron.summarize_long_text.return_value = ("Une facture de 42 euros.", True)
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "resume facture.pdf")

    from heypeer.executor.documents import Extraction

    with patch(
        "heypeer.executor.documents.extract",
        return_value=Extraction("Facture, 42 EUR"),
    ):
        peer.on_wake_word()

    nemotron.summarize_long_text.assert_called_once_with("Facture, 42 EUR", "fr")
    assert fake_tts.call_args_list[0].args == ("Voici un résumé de facture.pdf :",)
    assert fake_tts.call_args_list[1].args == ("Une facture de 42 euros.",)


def test_summarize_document_declines_for_an_unknown_file(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="summarize_document", skill_id=None, n_repetitions=1, target_name="introuvable.pdf",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "resume introuvable.pdf")

    peer.on_wake_word()

    fake_tts.assert_called_once_with("Je ne vois pas de fichier introuvable.pdf.", language="fr")
    nemotron.summarize_for_speech.assert_not_called()


def test_summarize_document_with_no_extractable_text_says_so(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """A scanned PDF with no text layer - see documents.py's module
    docstring for why this and a genuinely empty file look the same from
    here, and are reported the same honest way."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "scan.pdf").write_text("x")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="summarize_document", skill_id=None, n_repetitions=1, target_name="scan.pdf",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "resume scan.pdf")

    with patch("heypeer.executor.documents.extract_text", return_value=""):
        peer.on_wake_word()

    fake_tts.assert_called_once_with("Je n'ai rien pu extraire de scan.pdf.", language="fr")
    nemotron.summarize_for_speech.assert_not_called()


def test_read_screen_speaks_intro_then_the_answer(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="read_screen", skill_id=None, n_repetitions=1, speech="Je regarde l'écran...",
    )
    nemotron.describe_image.return_value = "Il y a un message d'erreur."
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "qu'est-ce qu'il y a sur mon ecran ?")

    with patch("heypeer.executor.screen.capture", return_value=b"fake-png-bytes"):
        peer.on_wake_word()

    assert fake_tts.call_args_list[0].args == ("Je regarde l'écran...",)
    assert fake_tts.call_args_list[1].args == ("Il y a un message d'erreur.",)
    nemotron.describe_image.assert_called_once_with(
        b"fake-png-bytes", "qu'est-ce qu'il y a sur mon ecran ?", "fr"
    )


def test_read_screen_passes_the_original_instruction_as_the_question(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """A specific question ("y a-t-il une erreur ?") must reach
    describe_image as-is, not a generic "describe the screen" - that is
    what makes the answer actually address what was asked."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="read_screen", skill_id=None, n_repetitions=1,
    )
    nemotron.describe_image.return_value = "Non, pas d'erreur visible."
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "y a-t-il une erreur affichee ?")

    with patch("heypeer.executor.screen.capture", return_value=b"fake-png-bytes"):
        peer.on_wake_word()

    assert nemotron.describe_image.call_args.args[1] == "y a-t-il une erreur affichee ?"


def test_read_screen_capture_failure_is_reported_honestly(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="read_screen", skill_id=None, n_repetitions=1,
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "qu'est-ce qu'il y a sur mon ecran ?")

    with patch("heypeer.executor.screen.capture", return_value=None):
        peer.on_wake_word()

    assert fake_tts.call_args_list[-1].args == ("Je n'ai pas pu capturer l'écran.",)
    nemotron.describe_image.assert_not_called()


# --- Coding assistant (round 37) --------------------------------------------
#
# analyze_code is read-only and low-risk - it just wires diagnose_code, the
# same shape as read_screen/summarize_document. fix_code is the highest-
# stakes action in the project: it dispatches a real external agent that
# writes to disk. These tests focus disproportionately on fix_code's safety
# properties - the undo entry is pushed, the diff is only opened and the
# summary only spoken when the file genuinely changed, and every one of the
# ways the agent dispatch can fail (not installed, times out, silently does
# nothing) degrades to an honest spoken message rather than a crash or a
# false "done".


def test_analyze_code_speaks_the_diagnosis(tmp_path: Path, fake_tts: MagicMock) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "calc.py").write_text("def f(x):\n    return 1 / x\n")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="analyze_code", skill_id=None, n_repetitions=1,
        target_name="calc.py", speech="Je regarde le code...",
    )
    nemotron.diagnose_code.return_value = "Ca plante si x vaut zero."
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "pourquoi ca plante ?")

    peer.on_wake_word()

    nemotron.diagnose_code.assert_called_once_with(
        "def f(x):\n    return 1 / x\n", "pourquoi ca plante ?", "fr"
    )
    assert fake_tts.call_args_list[-1].args == ("Ca plante si x vaut zero.",)


def test_analyze_code_declines_for_an_unknown_file(tmp_path: Path, fake_tts: MagicMock) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="analyze_code", skill_id=None, n_repetitions=1, target_name="introuvable.py",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "analyse introuvable.py")

    peer.on_wake_word()

    fake_tts.assert_called_once_with("Je ne vois pas de fichier introuvable.py.", language="fr")
    nemotron.diagnose_code.assert_not_called()


def test_fix_code_declines_when_the_agent_is_not_installed(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """The realistic, common state for anyone without the Claude Code CLI -
    must say so honestly, never attempt the dispatch or claim success."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "calc.py").write_text("def f(): return 1/0\n")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="fix_code", skill_id=None, n_repetitions=1, target_name="calc.py",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "corrige calc.py")

    with patch("heypeer.executor.coding_agent.is_available", return_value=False):
        peer.on_wake_word()

    fake_tts.assert_called_once_with(
        "Je ne peux pas corriger de code pour l'instant, l'agent de code n'est pas installé.",
        language="fr",
    )
    assert len(peer._undo_stack) == 0


def test_fix_code_pushes_an_undo_entry_when_the_file_changes(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    path = watched_dir / "calc.py"
    path.write_text("def f():\n    return 1 / 0\n")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="fix_code", skill_id=None, n_repetitions=1, target_name="calc.py",
    )
    nemotron.summarize_for_speech.return_value = "J'ai remplace 1/0 par 1."
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "corrige calc.py")

    def fake_run(prompt, cwd):
        path.write_text("def f():\n    return 1\n")  # the agent's edit
        return "Explained and fixed the division by zero."

    with (
        patch("heypeer.executor.coding_agent.is_available", return_value=True),
        patch("heypeer.executor.coding_agent.run", side_effect=fake_run),
        patch("heypeer.executor.coding_agent.open_diff_in_vscode") as open_diff,
    ):
        peer.on_wake_word()

    assert len(peer._undo_stack) == 1
    entry = peer._undo_stack.pop()
    entry.undo()
    assert path.read_text() == "def f():\n    return 1 / 0\n"  # restored
    open_diff.assert_called_once()
    assert fake_tts.call_args_list[-1].args == ("J'ai remplace 1/0 par 1.",)


def test_fix_code_reports_when_nothing_actually_changed(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """The agent ran but decided there was nothing to fix (or nothing it
    could do) - no undo entry, no diff, and Hey Peer must not claim a fix
    that didn't happen."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "calc.py").write_text("def f():\n    return 1\n")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="fix_code", skill_id=None, n_repetitions=1, target_name="calc.py",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "corrige calc.py")

    with (
        patch("heypeer.executor.coding_agent.is_available", return_value=True),
        patch("heypeer.executor.coding_agent.run", return_value="Looks fine, no changes needed."),
        patch("heypeer.executor.coding_agent.open_diff_in_vscode") as open_diff,
    ):
        peer.on_wake_word()

    assert len(peer._undo_stack) == 0
    open_diff.assert_not_called()
    fake_tts.assert_called_with("Je n'ai rien changé dans calc.py.", language="fr")


def test_fix_code_timeout_is_reported_and_does_not_hang(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    from heypeer.executor import coding_agent

    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "calc.py").write_text("def f(): return 1/0\n")
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="fix_code", skill_id=None, n_repetitions=1, target_name="calc.py",
    )
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: "corrige calc.py")

    with (
        patch("heypeer.executor.coding_agent.is_available", return_value=True),
        patch(
            "heypeer.executor.coding_agent.run",
            side_effect=coding_agent.CodingAgentTimedOut("too slow"),
        ),
    ):
        peer.on_wake_word()

    fake_tts.assert_called_with("Ça prend trop de temps, j'abandonne.", language="fr")
    assert len(peer._undo_stack) == 0


def test_undo_after_fix_code_restores_the_file_via_annule(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """End to end through the real "annule" path, not just the undo entry
    in isolation - the same safety net every other action here has."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    path = watched_dir / "calc.py"
    original = "def f():\n    return 1 / 0\n"
    path.write_text(original)
    nemotron = MagicMock()
    nemotron.interpret_text.side_effect = [
        Intent(action="fix_code", skill_id=None, n_repetitions=1, target_name="calc.py"),
        Intent(action="undo", skill_id=None, n_repetitions=1),
    ]

    def fake_run(prompt, cwd):
        path.write_text("def f():\n    return 1\n")
        return "Fixed."

    it = iter(["corrige calc.py", "annule"])
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched_dir, get_instruction=lambda: next(it))

    with (
        patch("heypeer.executor.coding_agent.is_available", return_value=True),
        patch("heypeer.executor.coding_agent.run", side_effect=fake_run),
        patch("heypeer.executor.coding_agent.open_diff_in_vscode"),
    ):
        peer.on_wake_word()
        peer.on_wake_word()

    assert path.read_text() == original


# --- Persistent memory and general tasks (round 38) -------------------------


def test_remember_fact_saves_it_and_confirms(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="remember_fact", skill_id=None, n_repetitions=1,
        content="Je préfère qu'on m'appelle Tom", speech="Je m'en souviendrai.",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "retiens que je prefere qu'on m'appelle Tom")

    with patch("heypeer.memory.DEFAULT_PATH", tmp_path / "memory.json"):
        peer.on_wake_word()

    from heypeer import memory

    assert memory.as_context(tmp_path / "memory.json") == ["Je préfère qu'on m'appelle Tom"]
    fake_tts.assert_called_once_with("Je m'en souviendrai.", language="fr")


def test_remembered_facts_are_passed_to_the_next_interpretation(tmp_path: Path) -> None:
    """The whole point: a fact told once must reach Nemotron on a later,
    entirely separate turn - not just be saved somewhere unread."""
    from heypeer import memory

    memory_path = tmp_path / "memory.json"
    memory.remember("Tom prefere qu'on l'appelle Tom.", memory_path)

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="reply", skill_id=None, n_repetitions=1, speech="Tu preferes Tom.",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "comment je prefere qu'on m'appelle ?")

    with patch("heypeer.memory.DEFAULT_PATH", memory_path):
        peer.on_wake_word()

    assert nemotron.interpret_text.call_args.kwargs["memory"] == ["Tom prefere qu'on l'appelle Tom."]


def test_general_task_declines_when_the_agent_is_not_installed(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="general_task", skill_id=None, n_repetitions=1,
        content="cherche des vols pour Paris",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "cherche des vols pour Paris")

    with patch("heypeer.executor.general_agent.is_available", return_value=False):
        peer.on_wake_word()

    fake_tts.assert_called_once_with(
        "Je ne peux pas faire de tâche générale pour l'instant, l'agent n'est pas installé.",
        language="fr",
    )


def test_general_task_speaks_the_summarized_result(tmp_path: Path, fake_tts: MagicMock) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="general_task", skill_id=None, n_repetitions=1,
        content="cherche des vols pour Paris le mois prochain",
        speech="Je m'en occupe...",
    )
    nemotron.summarize_for_speech.return_value = "Trois vols trouvés, le moins cher a 120 euros."
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "cherche des vols pour Paris")

    with (
        patch("heypeer.executor.general_agent.is_available", return_value=True),
        patch("heypeer.executor.general_agent.run", return_value="Found three flights..."),
    ):
        peer.on_wake_word()

    nemotron.summarize_for_speech.assert_called_once_with("Found three flights...", "fr")
    assert fake_tts.call_args_list[-1].args == ("Trois vols trouvés, le moins cher a 120 euros.",)


def test_general_task_timeout_is_reported_honestly(tmp_path: Path, fake_tts: MagicMock) -> None:
    from heypeer.executor import general_agent

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="general_task", skill_id=None, n_repetitions=1, content="une tache longue",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "fais cette tache longue")

    with (
        patch("heypeer.executor.general_agent.is_available", return_value=True),
        patch(
            "heypeer.executor.general_agent.run",
            side_effect=general_agent.GeneralAgentTimedOut("too slow"),
        ),
    ):
        peer.on_wake_word()

    fake_tts.assert_called_with("Ça prend trop de temps, j'abandonne.", language="fr")


def test_general_task_pushes_no_undo_entry(tmp_path: Path, fake_tts: MagicMock) -> None:
    """Unlike fix_code: an open-ended task is not reliably one reversible
    edit, so there is nothing honest to capture as "the" change to undo -
    see general_agent.py's module docstring."""
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="general_task", skill_id=None, n_repetitions=1, content="une tache",
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "fais une tache")

    with (
        patch("heypeer.executor.general_agent.is_available", return_value=True),
        patch("heypeer.executor.general_agent.run", return_value="done"),
    ):
        peer.on_wake_word()

    assert len(peer._undo_stack) == 0


# --- Screen-based code debugging (round 40) ---------------------------------
#
# "ca fonctionne bien mais seulement si le fichier est dans le dossier
# telechargement" - analyze_code/fix_code only ever worked for a file
# already in the watched folder, useless for an actual coding project.
# _resolve_code_path is the fix: a real path (absolute, or otherwise
# directly resolvable) is checked first, before falling back to the
# watched-folder-only resolution every other file action still uses.
# debug_screen_code is the other half: no filename needed at all, looked
# up from the screen instead.


def test_resolve_code_path_accepts_a_real_path_outside_the_watched_dir(
    tmp_path: Path,
) -> None:
    """The actual fix for the reported bug: a real project file, nowhere
    near the watched folder (~/Downloads by default), must resolve."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    project_file = tmp_path / "MonProjet" / "calc.py"
    project_file.parent.mkdir()
    project_file.write_text("def f(): return 1 / 0\n")

    peer = HeyPeer(nemotron=MagicMock(), watched_dir=watched_dir)

    assert peer._resolve_code_path(str(project_file)) == project_file


def test_resolve_code_path_still_falls_back_to_the_watched_dir(tmp_path: Path) -> None:
    """A bare filename that IS in the watched folder must keep working
    exactly as before - this is an addition, not a replacement."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    (watched_dir / "facture.pdf").write_text("x")

    peer = HeyPeer(nemotron=MagicMock(), watched_dir=watched_dir)

    assert peer._resolve_code_path("facture.pdf") == watched_dir / "facture.pdf"


def test_resolve_code_path_declines_when_neither_resolves(tmp_path: Path) -> None:
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    peer = HeyPeer(nemotron=MagicMock(), watched_dir=watched_dir)

    assert peer._resolve_code_path("nowhere/introuvable.py") is None


def test_fix_code_works_on_a_file_outside_the_watched_directory(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    """End to end, not just the resolver in isolation: the actual reported
    complaint, fixed."""
    watched_dir = tmp_path / "Downloads"
    watched_dir.mkdir()
    project_file = tmp_path / "MonProjet" / "calc.py"
    project_file.parent.mkdir()
    project_file.write_text("def f():\n    return 1 / 0\n")

    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="fix_code", skill_id=None, n_repetitions=1, target_name=str(project_file),
    )
    nemotron.summarize_for_speech.return_value = "Corrige."
    peer = HeyPeer(
        nemotron=nemotron, watched_dir=watched_dir,
        get_instruction=lambda: f"corrige {project_file}",
    )

    def fake_run(prompt, cwd):
        assert cwd == project_file.parent  # real project context, not Downloads
        project_file.write_text("def f():\n    return 1\n")
        return "Fixed."

    with (
        patch("heypeer.executor.coding_agent.is_available", return_value=True),
        patch("heypeer.executor.coding_agent.run", side_effect=fake_run),
        patch("heypeer.executor.coding_agent.open_diff_in_vscode"),
    ):
        peer.on_wake_word()

    assert project_file.read_text() == "def f():\n    return 1\n"
    assert len(peer._undo_stack) == 1


def test_debug_screen_code_speaks_the_diagnosis_and_opens_a_followup(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="debug_screen_code", skill_id=None, n_repetitions=1,
        speech="Je regarde l'écran...",
    )
    nemotron.diagnose_screen_code.return_value = (
        "Le probleme vient de calc.py, division par zero. Je corrige ?"
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "qu'est-ce qui ne va pas ici ?")
    peer._wake_listener = MagicMock()

    with patch("heypeer.executor.screen.capture", return_value=b"fake-png-bytes"):
        peer.on_wake_word()

    nemotron.diagnose_screen_code.assert_called_once_with(
        b"fake-png-bytes", "qu'est-ce qui ne va pas ici ?", "fr"
    )
    assert fake_tts.call_args_list[-1].args == (
        "Le probleme vient de calc.py, division par zero. Je corrige ?",
    )
    # Unlike read_screen/analyze_code: this ends in a question, so the
    # exchange must stay open for "oui"/"corrige-le" without repeating the
    # wake word.
    peer._wake_listener.arm_followup.assert_called_once()


def test_debug_screen_code_capture_failure_is_reported_honestly(
    tmp_path: Path, fake_tts: MagicMock
) -> None:
    nemotron = MagicMock()
    nemotron.interpret_text.return_value = Intent(
        action="debug_screen_code", skill_id=None, n_repetitions=1,
    )
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: "qu'est-ce qui ne va pas ici ?")

    with patch("heypeer.executor.screen.capture", return_value=None):
        peer.on_wake_word()

    fake_tts.assert_called_with("Je n'ai pas pu capturer l'écran.", language="fr")
    nemotron.diagnose_screen_code.assert_not_called()


def test_debug_then_fix_is_one_continuous_exchange(tmp_path: Path, fake_tts: MagicMock) -> None:
    """The whole point of the flow: diagnose from the screen, ask, and a
    plain "oui" - no wake word, no filename repeated - reaches fix_code
    with the file the diagnosis itself named, because it is now in the
    exchange history."""
    project_file = tmp_path / "MonProjet" / "calc.py"
    project_file.parent.mkdir()
    project_file.write_text("def f():\n    return 1 / 0\n")

    nemotron = MagicMock()
    nemotron.interpret_text.side_effect = [
        Intent(
            action="debug_screen_code", skill_id=None, n_repetitions=1,
            speech="Je regarde l'écran...",
        ),
        Intent(
            action="fix_code", skill_id=None, n_repetitions=1, target_name=str(project_file),
        ),
    ]
    nemotron.diagnose_screen_code.return_value = (
        f"Le fichier est {project_file}, division par zero. Je corrige ?"
    )
    nemotron.summarize_for_speech.return_value = "Corrige."

    it = iter(["qu'est-ce qui ne va pas ici ?", "oui, corrige"])
    peer = HeyPeer(nemotron=nemotron, get_instruction=lambda: next(it))

    def fake_run(prompt, cwd):
        project_file.write_text("def f():\n    return 1\n")
        return "Fixed."

    with (
        patch("heypeer.executor.screen.capture", return_value=b"fake-png-bytes"),
        patch("heypeer.executor.coding_agent.is_available", return_value=True),
        patch("heypeer.executor.coding_agent.run", side_effect=fake_run),
        patch("heypeer.executor.coding_agent.open_diff_in_vscode"),
    ):
        peer.on_wake_word(followup=False)
        peer.on_wake_word(followup=True)

    assert project_file.read_text() == "def f():\n    return 1\n"


def test_speak_arms_barge_in_for_the_duration_of_playback(tmp_path: Path) -> None:
    """While Hey Peer talks, the wake word must stay live so it can be
    interrupted - and go back to fully muted once the answer is out."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    listener = MagicMock()
    peer._wake_listener = listener
    calls = []
    listener.mute_except_barge_in.side_effect = lambda: calls.append("barge_in_on")
    listener.mute.side_effect = lambda: calls.append("muted")

    with patch("heypeer.tray.tts.speak") as speak:
        speak.side_effect = lambda *a, **k: calls.append("spoke")
        peer._speak("bonjour")

    assert calls == ["barge_in_on", "spoke", "muted"]


def test_speak_hands_the_listener_a_way_to_interrupt(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    listener = MagicMock()
    peer._wake_listener = listener
    seen = []
    with patch("heypeer.tray.tts.speak") as speak:
        speak.side_effect = lambda *a, **k: seen.append(listener.on_barge_in)
        peer._speak("bonjour")

    assert seen == [peer._on_barge_in]
    # ...and it is cleared afterwards, so a later detection can't stop audio
    # that no longer belongs to this turn.
    assert listener.on_barge_in is None


def test_barge_in_stops_playback(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.tray.audio_out.stop") as stop:
        peer._on_barge_in()
    stop.assert_called_once()


def test_speak_still_works_with_no_listener_attached(tmp_path: Path) -> None:
    """The CLI path and tests construct a HeyPeer with no wake listener."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._wake_listener = None
    with patch("heypeer.tray.tts.speak") as speak:
        peer._speak("bonjour")
    speak.assert_called_once()


def test_speak_restores_mute_even_if_tts_raises(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    listener = MagicMock()
    peer._wake_listener = listener
    with patch("heypeer.tray.tts.speak", side_effect=RuntimeError("no audio device")):
        peer._speak("bonjour")
    listener.mute.assert_called_once()
    assert listener.on_barge_in is None


def _reminder_intent(**kwargs) -> Intent:
    base = dict(action="set_reminder", skill_id=None, n_repetitions=1)
    base.update(kwargs)
    return Intent(**base)


def test_set_reminder_schedules_and_confirms(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch.object(peer, "_speak") as speak, patch.object(peer, "_ensure_countdown"):
        peer._run_set_reminder("les pâtes", 600, None, "fr")
    assert len(peer._reminders.active()) == 1
    assert peer._reminders.active()[0].label == "les pâtes"
    assert "10 minutes" in speak.call_args.args[0]
    peer._reminders.clear()


def test_set_reminder_refuses_without_a_duration(tmp_path: Path) -> None:
    """Never silently schedule a guess - a timer with no length is a
    misunderstanding, not a default."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch.object(peer, "_speak") as speak:
        peer._run_set_reminder("les pâtes", None, None, "fr")
    assert peer._reminders.active() == []
    assert "durée" in speak.call_args.args[0]


def test_set_reminder_says_so_when_there_are_already_too_many(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    from heypeer.executor.reminders import MAX_ACTIVE

    for i in range(MAX_ACTIVE):
        peer._reminders.add(f"t{i}", 600)
    with patch.object(peer, "_speak") as speak, patch.object(peer, "_ensure_countdown"):
        peer._run_set_reminder("one too many", 600, None, "fr")
    assert "trop de minuteurs" in speak.call_args.args[0]
    peer._reminders.clear()


def test_a_reminder_speaks_when_it_comes_due(tmp_path: Path) -> None:
    """The whole point: it talks with no wake word and no exchange open."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    reminder = MagicMock(label="les pâtes", language="fr")
    with patch.object(peer, "_speak") as speak, patch.object(peer, "_refresh_countdown"):
        peer._on_reminder_due(reminder)
    assert "les pâtes" in speak.call_args.args[0]


def test_a_due_reminder_does_not_leave_the_microphone_open(tmp_path: Path) -> None:
    """The user may not even be at the machine - a timer nobody answered
    must not leave Hey Peer listening."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    reminder = MagicMock(label="", language="fr")
    with patch.object(peer, "_speak"), patch.object(peer, "_refresh_countdown"), patch.object(
        peer, "_arm_followup"
    ) as arm:
        peer._on_reminder_due(reminder)
    arm.assert_not_called()


def test_cancel_reminder_with_one_running_needs_no_label(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._reminders.add("les pâtes", 600)
    with patch.object(peer, "_speak"), patch.object(peer, "_refresh_countdown"):
        peer._run_cancel_reminder(None, None, "fr")
    assert peer._reminders.active() == []


def test_cancel_reminder_asks_which_when_several_are_running(tmp_path: Path) -> None:
    """Cancelling the wrong timer silently is worse than asking."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._reminders.add("les pâtes", 600)
    peer._reminders.add("la lessive", 900)
    with patch.object(peer, "_speak") as speak, patch.object(peer, "_arm_followup") as arm:
        peer._run_cancel_reminder(None, None, "fr")
    assert len(peer._reminders.active()) == 2, "nothing should have been cancelled"
    assert "Lequel" in speak.call_args.args[0]
    arm.assert_called_once()
    peer._reminders.clear()


def test_cancel_reminder_matches_a_named_one_among_several(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._reminders.add("les pâtes", 600)
    peer._reminders.add("la lessive", 900)
    with patch.object(peer, "_speak"), patch.object(peer, "_refresh_countdown"):
        peer._run_cancel_reminder("les pâtes", None, "fr")
    assert [r.label for r in peer._reminders.active()] == ["la lessive"]
    peer._reminders.clear()


def test_cancel_reminder_with_nothing_running_says_so(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch.object(peer, "_speak") as speak:
        peer._run_cancel_reminder(None, None, "fr")
    assert "aucun minuteur" in speak.call_args.args[0]


def test_list_reminders_reads_back_what_is_left(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._reminders.add("les pâtes", 600)
    with patch.object(peer, "_speak") as speak:
        peer._run_list_reminders("fr")
    spoken = speak.call_args.args[0]
    assert "les pâtes" in spoken and "minutes" in spoken
    peer._reminders.clear()


def test_list_reminders_with_nothing_running(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch.object(peer, "_speak") as speak:
        peer._run_list_reminders("fr")
    assert "aucun minuteur" in speak.call_args.args[0]


def test_quitting_cancels_pending_timers(tmp_path: Path) -> None:
    """A daemon timer firing into a half-shut-down app would try to speak
    through an audio stack that is going away."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._reminders.add("les pâtes", 600)
    peer._on_quit()
    assert peer._reminders.active() == []


def test_set_reminder_dispatches_from_an_intent(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    intent = _reminder_intent(content="les pâtes", duration_seconds=600, speech="C'est noté.")
    with patch.object(peer, "_run_set_reminder") as run:
        peer._dispatch_intent(intent, "mets un minuteur")
    run.assert_called_once_with("les pâtes", 600, "C'est noté.", "fr")


def test_running_a_routine_dispatches_each_step(tmp_path: Path) -> None:
    """Steps are re-interpreted rather than replayed, so each one means what
    it would mean if spoken directly."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    routine = MagicMock(name="r", steps=["mets de la musique", "ouvre Slack"])
    routine.name = "matin"
    with patch("heypeer.executor.routines.find", return_value=routine), patch.object(
        peer, "_interpret"
    ) as interpret, patch.object(peer, "_dispatch_intent") as dispatch:
        peer._run_run_routine("matin", "fr")
    assert interpret.call_count == 2
    assert [c.args[0] for c in interpret.call_args_list] == [
        "mets de la musique",
        "ouvre Slack",
    ]
    assert dispatch.call_count == 2


def test_a_routine_cannot_run_another_routine(tmp_path: Path) -> None:
    """Without the guard, a routine whose step is "lance ma routine du
    matin" loops unboundedly, speaking and acting all the way down."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._in_routine = True
    with patch("heypeer.executor.routines.find") as find, patch.object(peer, "_speak") as speak:
        peer._run_run_routine("matin", "fr")
    find.assert_not_called()
    assert "routine" in speak.call_args.args[0].lower()


def test_the_routine_guard_is_released_afterwards(tmp_path: Path) -> None:
    """Otherwise the first routine of a session would be the only one."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    routine = MagicMock(steps=["ouvre Slack"])
    routine.name = "matin"
    with patch("heypeer.executor.routines.find", return_value=routine), patch.object(
        peer, "_interpret"
    ), patch.object(peer, "_dispatch_intent"):
        peer._run_run_routine("matin", "fr")
    assert peer._in_routine is False


def test_a_failing_step_does_not_abandon_the_rest(tmp_path: Path) -> None:
    """A routine is several independent things; stopping at the first
    problem would silently drop everything after it."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    routine = MagicMock(steps=["step one", "step two", "step three"])
    routine.name = "matin"
    with patch("heypeer.executor.routines.find", return_value=routine), patch.object(
        peer, "_interpret", side_effect=[RuntimeError("boom"), MagicMock(), MagicMock()]
    ), patch.object(peer, "_dispatch_intent") as dispatch:
        peer._run_run_routine("matin", "fr")
    assert dispatch.call_count == 2, "later steps should still have run"


def test_the_guard_is_released_even_if_a_step_explodes(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    routine = MagicMock(steps=["boom"])
    routine.name = "matin"
    with patch("heypeer.executor.routines.find", return_value=routine), patch.object(
        peer, "_interpret", side_effect=RuntimeError("boom")
    ):
        peer._run_run_routine("matin", "fr")
    assert peer._in_routine is False


def test_running_an_unknown_routine_says_so(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.routines.find", return_value=None), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_run_routine("inconnue", "fr")
    assert "inconnue" in speak.call_args.args[0]


def test_creating_a_routine_needs_a_name_and_steps(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.routines.remember") as remember, patch.object(
        peer, "_speak"
    ):
        peer._run_create_routine("matin", None, None, "fr")
        peer._run_create_routine(None, ["a"], None, "fr")
    remember.assert_not_called()


def test_creating_a_routine_confirms_with_its_size(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    saved = MagicMock(steps=["a", "b"])
    saved.name = "matin"
    with patch("heypeer.executor.routines.remember", return_value=saved), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_create_routine("matin", ["a", "b"], None, "fr")
    assert "2" in speak.call_args.args[0]


def test_listing_routines_when_there_are_none(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.routines.names", return_value=[]), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_list_routines("fr")
    assert "pas encore" in speak.call_args.args[0]


def test_listing_routines_reads_the_names(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.routines.names", return_value=["matin", "boulot"]), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_list_routines("fr")
    assert "matin" in speak.call_args.args[0] and "boulot" in speak.call_args.args[0]


def test_listen_to_screen_says_so_when_unsupported(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.system_audio.is_available", return_value=False), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_listen_to_screen("qu'est-ce qu'ils disent ?", None, "fr")
    assert "son de l'ordinateur" in speak.call_args.args[0]


def test_listen_to_screen_transcribes_locally_then_asks_about_the_text(tmp_path: Path) -> None:
    """The audio must never leave the machine just because the user asked
    what was said - only the transcript goes to the model."""
    nemotron = MagicMock()
    nemotron.answer_about_text.return_value = "Ils parlent du budget."
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.system_audio.is_available", return_value=True), patch(
        "heypeer.executor.system_audio.capture", return_value=b"\x01\x00" * 100
    ), patch("heypeer.wakeword.stt.transcribe", return_value="on parle du budget"), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_listen_to_screen("qu'est-ce qu'ils disent ?", None, "fr")
    nemotron.answer_about_text.assert_called_once()
    assert nemotron.answer_about_text.call_args.args[0] == "on parle du budget"
    assert speak.call_args.args[0] == "Ils parlent du budget."


def test_silence_is_reported_as_silence_not_as_a_failure(tmp_path: Path) -> None:
    """Nothing playing is the likely case, and it is not an error."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.system_audio.is_available", return_value=True), patch(
        "heypeer.executor.system_audio.capture", return_value=b"\x00\x00" * 100
    ), patch("heypeer.wakeword.stt.transcribe", return_value="   "), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_listen_to_screen("quoi ?", None, "fr")
    assert "rien entendu" in speak.call_args.args[0]
    nemotron.answer_about_text.assert_not_called()


def test_a_capture_failure_is_reported_honestly(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.executor.system_audio.is_available", return_value=True), patch(
        "heypeer.executor.system_audio.capture", side_effect=RuntimeError("no device")
    ), patch.object(peer, "_speak") as speak:
        peer._run_listen_to_screen("quoi ?", None, "fr")
    assert "capter le son" in speak.call_args.args[0]


def test_everything_spoken_reaches_the_transcript() -> None:
    """The corner caption filtered by length, because a panel popping up in
    the corner for "c'est fait" was noise. Beside the blob, while it is
    already on screen, the panel *is* the conversation - so it shows what
    was said, all of it."""
    from heypeer.main import HeyPeer

    peer = HeyPeer(nemotron=MagicMock())
    with patch("heypeer.tray.tts.speak"), patch.object(peer, "_show_transcript") as shown:
        peer._speak("C'est fait.")
        peer._speak("La fonction plante sur une liste vide.")
    assert [c.args[0] for c in shown.call_args_list] == [
        "C'est fait.",
        "La fonction plante sur une liste vide.",
    ]


def test_hey_peers_own_words_are_marked_as_its_own() -> None:
    """The two sides are typed at different speeds - the user already knows
    what they said."""
    from heypeer.main import HeyPeer

    peer = HeyPeer(nemotron=MagicMock())
    with patch("heypeer.tray.tts.speak"), patch.object(peer, "_show_transcript") as shown:
        peer._speak("Tres bien, et toi ?")
    assert shown.call_args.args[1] == "peer"


def test_a_transcript_failure_never_stops_hey_peer_speaking() -> None:
    """The panel is a convenience; speech is the product."""
    from heypeer.main import HeyPeer

    peer = HeyPeer(nemotron=MagicMock())
    with patch(
        "heypeer.tray.transcript_window.TranscriptWindow", side_effect=RuntimeError("no display")
    ), patch("heypeer.tray.tts.speak") as speak:
        peer._speak("Tres bien, et toi ?")
    speak.assert_called_once()


def test_a_failed_transcript_window_is_not_retried_every_answer() -> None:
    peer_cls = __import__("heypeer.main", fromlist=["HeyPeer"]).HeyPeer
    peer = peer_cls(nemotron=MagicMock())
    with patch(
        "heypeer.tray.transcript_window.TranscriptWindow", side_effect=RuntimeError("no display")
    ) as window:
        peer._show_transcript("une phrase")
        peer._show_transcript("une autre phrase")
    assert window.call_count == 1


def test_a_partly_read_document_says_so_out_loud(tmp_path: Path) -> None:
    """The whole point of this change. Summarizing part of a document while
    sounding like it read all of it is a wrong answer dressed as a complete
    one - worse than either reading it all or admitting the limit."""
    from heypeer.executor.documents import Extraction

    nemotron = MagicMock()
    nemotron.summarize_long_text.return_value = ("Un rapport trimestriel.", True)
    watched = tmp_path / "Downloads"
    watched.mkdir()
    (watched / "rapport.pdf").write_text("x")
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched)

    with patch(
        "heypeer.executor.documents.extract",
        return_value=Extraction("texte", complete=False, pages_read=300, pages_total=420),
    ), patch.object(peer, "_speak") as speak:
        peer._run_summarize_document("rapport.pdf", None, "fr")

    spoken = " ".join(c.args[0] for c in speak.call_args_list)
    assert "420" in spoken and "300" in spoken, "must say how much it actually read"
    assert "Un rapport trimestriel." in spoken


def test_a_document_read_in_full_makes_no_excuse(tmp_path: Path) -> None:
    """The caveat must not appear when it read everything - a warning that
    fires always is a warning nobody reads."""
    from heypeer.executor.documents import Extraction

    nemotron = MagicMock()
    nemotron.summarize_long_text.return_value = ("Une facture.", True)
    watched = tmp_path / "Downloads"
    watched.mkdir()
    (watched / "facture.pdf").write_text("x")
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched)

    with patch(
        "heypeer.executor.documents.extract", return_value=Extraction("texte")
    ), patch.object(peer, "_speak") as speak:
        peer._run_summarize_document("facture.pdf", None, "fr")

    spoken = " ".join(c.args[0] for c in speak.call_args_list)
    assert "pages" not in spoken and "partie" not in spoken


def test_a_document_too_long_to_summarize_whole_says_so(tmp_path: Path) -> None:
    """The other cause of incompleteness: chunking stopped at MAX_CHUNKS."""
    from heypeer.executor.documents import Extraction

    nemotron = MagicMock()
    nemotron.summarize_long_text.return_value = ("Un long rapport.", False)
    watched = tmp_path / "Downloads"
    watched.mkdir()
    (watched / "rapport.pdf").write_text("x")
    peer = HeyPeer(nemotron=nemotron, watched_dir=watched)

    with patch(
        "heypeer.executor.documents.extract", return_value=Extraction("texte")
    ), patch.object(peer, "_speak") as speak:
        peer._run_summarize_document("rapport.pdf", None, "fr")

    spoken = " ".join(c.args[0] for c in speak.call_args_list)
    assert "qu'une partie" in spoken


def test_summarizing_a_document_outside_the_watched_folder(tmp_path: Path) -> None:
    """Consistency with the file actions widened two days ago: this handler
    still resolved names against the watched directory only."""
    from heypeer.executor.documents import Extraction

    nemotron = MagicMock()
    nemotron.summarize_long_text.return_value = ("Un contrat.", True)
    elsewhere = tmp_path / "Documents"
    elsewhere.mkdir()
    doc = elsewhere / "contrat.pdf"
    doc.write_text("x")
    peer = HeyPeer(nemotron=nemotron, watched_dir=tmp_path / "Downloads")

    with patch.object(peer, "_resolved_path", return_value=doc), patch(
        "heypeer.executor.documents.extract", return_value=Extraction("texte")
    ), patch.object(peer, "_speak") as speak:
        peer._run_summarize_document("contrat.pdf", None, "fr")

    spoken = " ".join(c.args[0] for c in speak.call_args_list)
    assert "Un contrat." in spoken


def test_clicking_finds_the_control_then_presses_its_centre(tmp_path: Path) -> None:
    """The three pieces in order: resolve the name, animate, press."""
    from heypeer.executor.ui_elements import Element

    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    element = Element("Send", "ButtonControl", (600, 300, 700, 340))

    with patch("heypeer.executor.ui_elements.is_available", return_value=True), patch(
        "heypeer.executor.cursor_control.is_supported", return_value=True
    ), patch("heypeer.executor.ui_elements.find", return_value=element), patch(
        "heypeer.executor.cursor_control.cursor_position", return_value=(100, 100)
    ), patch("heypeer.executor.cursor_control.click_at") as click, patch.object(
        peer, "_animate_cursor"
    ) as animate, patch.object(peer, "_speak_async"):
        peer._run_click_element("Send", None, "fr")

    click.assert_called_once_with(650, 320)
    animate.assert_called_once_with((100, 100), (650, 320))


def test_the_pointer_arrives_before_the_click(tmp_path: Path) -> None:
    """A click delivered before the pointer lands looks like it pressed the
    wrong place."""
    from heypeer.executor.ui_elements import Element

    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    order = []

    with patch("heypeer.executor.ui_elements.is_available", return_value=True), patch(
        "heypeer.executor.cursor_control.is_supported", return_value=True
    ), patch(
        "heypeer.executor.ui_elements.find",
        return_value=Element("Send", "ButtonControl", (0, 0, 10, 10)),
    ), patch("heypeer.executor.cursor_control.cursor_position", return_value=(0, 0)), patch(
        "heypeer.executor.cursor_control.click_at", side_effect=lambda *a: order.append("click")
    ), patch.object(
        peer, "_animate_cursor", side_effect=lambda *a: order.append("animate")
    ), patch.object(peer, "_speak_async"):
        peer._run_click_element("Send", None, "fr")

    assert order == ["animate", "click"]


def test_a_missing_control_is_distinguished_from_being_unable_to_click(tmp_path: Path) -> None:
    """Different problems with different fixes - collapsing them sends the
    user looking in the wrong place."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)

    with patch("heypeer.executor.ui_elements.is_available", return_value=True), patch(
        "heypeer.executor.cursor_control.is_supported", return_value=True
    ), patch("heypeer.executor.ui_elements.find", return_value=None), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_click_element("Envoyer", None, "fr")
    not_found = speak.call_args.args[0]

    with patch("heypeer.executor.ui_elements.is_available", return_value=False), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_click_element("Envoyer", None, "fr")
    cannot = speak.call_args.args[0]

    assert not_found != cannot
    assert "Envoyer" in not_found


def test_clicking_with_no_name_asks_which(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch.object(peer, "_speak") as speak, patch.object(peer, "_arm_followup") as arm:
        peer._run_click_element(None, None, "fr")
    assert "?" in speak.call_args.args[0]
    arm.assert_called_once()


def test_a_broken_animation_still_clicks(tmp_path: Path) -> None:
    """A button pressed without the animation is a working feature; the
    reverse is neither."""
    from heypeer.executor.ui_elements import Element

    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)

    with patch("heypeer.executor.ui_elements.is_available", return_value=True), patch(
        "heypeer.executor.cursor_control.is_supported", return_value=True
    ), patch(
        "heypeer.executor.ui_elements.find",
        return_value=Element("Send", "ButtonControl", (0, 0, 10, 10)),
    ), patch("heypeer.executor.cursor_control.cursor_position", return_value=(0, 0)), patch(
        "heypeer.tray.cursor_window.CursorWindow", side_effect=RuntimeError("no display")
    ), patch("heypeer.executor.cursor_control.click_at") as click, patch.object(
        peer, "_speak_async"
    ):
        peer._run_click_element("Send", None, "fr")

    click.assert_called_once()


def test_a_failed_click_is_reported_rather_than_claimed(tmp_path: Path) -> None:
    from heypeer.executor.ui_elements import Element

    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)

    with patch("heypeer.executor.ui_elements.is_available", return_value=True), patch(
        "heypeer.executor.cursor_control.is_supported", return_value=True
    ), patch(
        "heypeer.executor.ui_elements.find",
        return_value=Element("Send", "ButtonControl", (0, 0, 10, 10)),
    ), patch("heypeer.executor.cursor_control.cursor_position", return_value=(0, 0)), patch(
        "heypeer.executor.cursor_control.click_at", side_effect=RuntimeError("blocked")
    ), patch.object(peer, "_animate_cursor"), patch.object(peer, "_speak_async"), patch.object(
        peer, "_speak"
    ) as speak:
        peer._run_click_element("Send", None, "fr")

    assert "réussi" in speak.call_args.args[0]


def test_the_cursor_colour_defaults_to_red() -> None:
    from heypeer.main import _cursor_color_from_env

    with patch.dict("os.environ", {}, clear=True):
        assert _cursor_color_from_env() == (255, 0, 0)


def test_the_cursor_colour_can_be_configured() -> None:
    from heypeer.main import _cursor_color_from_env

    with patch.dict("os.environ", {"HEYPEER_CURSOR_COLOR": "0,200,120"}):
        assert _cursor_color_from_env() == (0, 200, 120)


def test_a_malformed_cursor_colour_falls_back_rather_than_crashing() -> None:
    """Startup must not fail over a cosmetic setting."""
    from heypeer.main import _cursor_color_from_env

    for bad in ("nonsense", "1,2", "1,2,3,4", ""):
        with patch.dict("os.environ", {"HEYPEER_CURSOR_COLOR": bad}):
            assert _cursor_color_from_env() == (255, 0, 0)


def _habit(instruction="ouvre Slack", action="open_app", count=3, days=2):
    from heypeer.habits import Habit

    return Habit(instruction=instruction, action=action, count=count, days=days)


def test_a_dispatched_action_is_recorded_as_an_observation(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    intent = Intent(action="open_app", skill_id=None, n_repetitions=1, target_name="Slack")
    with patch("heypeer.habits.record") as record, patch.object(peer, "_run_open_app"):
        peer._dispatch_intent(intent, "ouvre Slack")
    record.assert_called_once_with("open_app", "ouvre Slack")


def test_routine_steps_are_not_counted_as_habits(tmp_path: Path) -> None:
    """A routine's steps are Hey Peer replaying the user - counting them
    would let one routine manufacture the evidence for suggesting itself."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._in_routine = True
    intent = Intent(action="open_app", skill_id=None, n_repetitions=1, target_name="Slack")
    with patch("heypeer.habits.record") as record, patch.object(peer, "_run_open_app"):
        peer._dispatch_intent(intent, "ouvre Slack")
    record.assert_not_called()


def test_a_habit_is_offered_when_the_exchange_ends(tmp_path: Path) -> None:
    """The one moment an unprompted sentence interrupts nothing."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.habits.detect", return_value=_habit()), patch.object(
        peer, "_speak"
    ) as speak, patch.object(peer, "_arm_followup") as arm:
        peer._close_exchange()
    assert "ouvre Slack" in speak.call_args.args[0]
    arm.assert_called_once(), "the exchange must stay open for the answer"


def test_only_one_habit_is_offered_per_run(tmp_path: Path) -> None:
    """A second suggestion in one session is what makes assistants annoying
    enough to switch off."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.habits.detect", return_value=_habit()), patch.object(
        peer, "_speak"
    ), patch.object(peer, "_arm_followup"):
        assert peer._maybe_suggest_habit() is True
        assert peer._maybe_suggest_habit() is False


def test_nothing_is_said_when_there_is_no_habit(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.habits.detect", return_value=None), patch.object(peer, "_speak") as speak:
        peer._close_exchange()
    speak.assert_not_called()


def test_saying_yes_creates_the_routine_from_the_instruction(tmp_path: Path) -> None:
    """The whole reason this design works: what was observed is already a
    sentence Hey Peer can carry out."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._pending_habit = _habit("range la facture dans Archives", "move_file")
    intent = Intent(action="reply", skill_id=None, n_repetitions=1, speech="Oui, vas-y.")
    saved = MagicMock(steps=["range la facture dans Archives"])
    saved.name = "range la facture dans Archives"

    with patch("heypeer.executor.routines.remember", return_value=saved) as remember, patch(
        "heypeer.habits.accept"
    ) as accept, patch.object(peer, "_speak"):
        consumed = peer._answer_habit_suggestion(intent)

    assert consumed is True
    assert remember.call_args.args[1] == ["range la facture dans Archives"]
    accept.assert_called_once()


def test_saying_no_declines_and_lets_the_turn_through(tmp_path: Path) -> None:
    """Anything that is not a clear yes is a no, and the turn is still the
    user's - it must be dispatched normally rather than swallowed."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    peer._pending_habit = _habit()
    intent = Intent(action="reply", skill_id=None, n_repetitions=1, speech="Non merci.")

    with patch("heypeer.habits.decline") as decline, patch(
        "heypeer.executor.routines.remember"
    ) as remember:
        consumed = peer._answer_habit_suggestion(intent)

    assert consumed is False
    decline.assert_called_once()
    remember.assert_not_called()


def test_the_pending_habit_is_cleared_either_way(tmp_path: Path) -> None:
    """Otherwise the next turn would be read as another answer to a
    question nobody is still asking."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    for speech in ("Oui.", "Non."):
        peer._pending_habit = _habit()
        intent = Intent(action="reply", skill_id=None, n_repetitions=1, speech=speech)
        with patch("heypeer.executor.routines.remember"), patch("heypeer.habits.accept"), patch(
            "heypeer.habits.decline"
        ), patch.object(peer, "_speak"):
            peer._answer_habit_suggestion(intent)
        assert peer._pending_habit is None


def test_a_broken_habit_store_never_breaks_a_turn(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    intent = Intent(action="open_app", skill_id=None, n_repetitions=1, target_name="Slack")
    with patch("heypeer.habits.record", side_effect=RuntimeError("disk full")), patch.object(
        peer, "_run_open_app"
    ) as run:
        peer._dispatch_intent(intent, "ouvre Slack")
    run.assert_called_once(), "the action must still happen"


def test_the_screen_glow_lights_up_and_goes_out_with_the_exchange(tmp_path: Path) -> None:
    """It means "Hey Peer is up" - permanently on would decorate the screen
    rather than say anything."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    window = MagicMock()
    peer._glow_window = window

    peer._screen_glow(True)
    window.show.assert_called_once()

    with patch.object(peer, "_maybe_suggest_habit", return_value=False):
        peer._close_exchange()
    window.hide.assert_called_once()


def test_a_machine_that_cannot_show_the_glow_stops_trying(tmp_path: Path) -> None:
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch(
        "heypeer.tray.screen_glow_window.ScreenGlowWindow",
        side_effect=RuntimeError("no display"),
    ) as window:
        peer._screen_glow(True)
        peer._screen_glow(True)
    assert window.call_count == 1


def test_turning_the_glow_off_never_creates_a_window(tmp_path: Path) -> None:
    """Shutting down, or an exchange ending on a machine that never showed
    it, must not start a process just to hide something."""
    nemotron = MagicMock()
    peer = _peer(tmp_path, nemotron)
    with patch("heypeer.tray.screen_glow_window.ScreenGlowWindow") as window:
        peer._screen_glow(False)
    window.assert_not_called()


def test_a_retired_model_is_named_at_startup(capsys) -> None:
    """`.env` is gitignored, so a corrected default never reaches an
    existing checkout - the user only learns their model is gone from a 404
    mid-turn, which looks like Hey Peer having gone deaf."""
    from heypeer.main import RETIRED_MODELS, _warn_about_retired_models

    retired = next(iter(RETIRED_MODELS))
    _warn_about_retired_models(MagicMock(nemotron_model_id=retired))
    out = capsys.readouterr().out
    assert retired in out
    assert RETIRED_MODELS[retired] in out
    assert "NEMOTRON_MODEL_ID" in out


def test_a_current_model_produces_no_warning(capsys) -> None:
    from heypeer.main import _warn_about_retired_models

    _warn_about_retired_models(MagicMock(nemotron_model_id="nvidia/Nemotron-3_5-Lightning"))
    assert capsys.readouterr().out == ""
