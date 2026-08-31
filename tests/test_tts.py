from unittest.mock import MagicMock

import pytest

import heypeer.tray.tts as tts


def _patch_download(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replaces the real downloader on the `piper.download_voices` module.

    Stubbing `sys.modules["piper.download_voices"]` does *not* work here:
    `from piper import download_voices` takes the attribute off the already
    imported `piper` package rather than going through `sys.modules`, so the
    stub was silently ignored and the test hit the network for a 75 MB voice.
    """
    download_mock = MagicMock()
    monkeypatch.setattr("piper.download_voices.download_voice", download_mock)
    return download_mock


@pytest.fixture(autouse=True)
def reset_voice_cache():
    tts._voices = {}
    yield
    tts._voices = {}


def test_ensure_voice_downloaded_skips_download_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(tts, "VOICES_DIR", tmp_path)
    (tmp_path / "en_US-lessac-medium.onnx").write_bytes(b"x")
    download_mock = _patch_download(monkeypatch)

    tts._ensure_voice_downloaded("en_US-lessac-medium")

    download_mock.assert_not_called()


def test_ensure_voice_downloaded_downloads_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(tts, "VOICES_DIR", tmp_path)
    download_mock = _patch_download(monkeypatch)

    tts._ensure_voice_downloaded("en_US-lessac-medium")

    download_mock.assert_called_once_with("en_US-lessac-medium", tmp_path)


def test_get_voice_caches_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts, "_ensure_voice_downloaded", lambda name: "fake/path.onnx")
    fake_piper_voice_cls = MagicMock()
    fake_module = MagicMock(PiperVoice=fake_piper_voice_cls)
    monkeypatch.setitem(__import__("sys").modules, "piper", fake_module)

    first = tts._get_voice()
    second = tts._get_voice()

    assert first is second
    fake_piper_voice_cls.load.assert_called_once_with("fake/path.onnx")


def test_preload_calls_get_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    get_voice_mock = MagicMock()
    monkeypatch.setattr(tts, "_get_voice", get_voice_mock)

    tts.preload()

    get_voice_mock.assert_called_once()


# --- Bilingual voice selection (round 34) ----------------------------------
#
# "des fois je parle an anglais, le resultat est bon mais la parole qui
# confirme est en francais" - Nemotron now reports which language it wrote
# speech/question in (see nemotron/intent.py), and this is the half that
# actually makes the *voice* match: picking the right Piper model, and not
# running English text through the French-anglicism respelling layer, which
# exists for the opposite problem and would only mangle it.


def test_voice_for_english_is_the_english_voice() -> None:
    assert tts._voice_for("en") == (tts.ENGLISH_VOICE_NAME, tts.ENGLISH_SPEAKER_ID)


def test_voice_for_french_is_the_french_voice() -> None:
    assert tts._voice_for("fr") == (tts.DEFAULT_VOICE_NAME, tts.DEFAULT_SPEAKER_ID)


def test_voice_for_unset_language_falls_back_to_french() -> None:
    """An older or malformed answer with no language reported must not go
    silent or crash - French is the existing, safe default."""
    assert tts._voice_for(None) == (tts.DEFAULT_VOICE_NAME, tts.DEFAULT_SPEAKER_ID)


def test_voice_for_an_unrecognised_language_falls_back_to_french() -> None:
    assert tts._voice_for("de") == (tts.DEFAULT_VOICE_NAME, tts.DEFAULT_SPEAKER_ID)


def _fake_piper(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stubs everything `speak()` touches below the text-selection logic
    this round actually changed: voice loading, synthesis, and playback."""
    import sys
    import types

    monkeypatch.setattr(tts, "_ensure_voice_downloaded", lambda name: f"/fake/{name}.onnx")
    fake_voice = MagicMock()

    def fake_synthesize_wav(text, wav_file, syn_config):
        # A minimal, valid wav so the rest of speak() (which reads it back
        # to trim silence) has something real to work with.
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes((0).to_bytes(2, "little") * 100)

    fake_voice.synthesize_wav.side_effect = fake_synthesize_wav
    fake_piper_voice_cls = MagicMock(load=MagicMock(return_value=fake_voice))
    fake_module = types.ModuleType("piper")
    fake_module.PiperVoice = fake_piper_voice_cls
    monkeypatch.setitem(sys.modules, "piper", fake_module)
    monkeypatch.setattr("heypeer.tray.audio_out.play", MagicMock())
    return fake_voice


def test_speak_loads_the_english_voice_for_english_text(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_voice = _fake_piper(monkeypatch)

    tts.speak("Opening Spotify.", language="en")

    assert tts.ENGLISH_VOICE_NAME in tts._voices
    fake_voice.synthesize_wav.assert_called_once()


def test_speak_does_not_respell_english_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the fix: `for_speech`'s anglicism respelling is a
    French-voice problem. Handed to an English voice, "Spotify" must reach
    the synthesiser exactly as written, not as "spo-ti-fai"."""
    fake_voice = _fake_piper(monkeypatch)

    tts.speak("Opening Spotify.", language="en")

    synthesized_text = fake_voice.synthesize_wav.call_args.args[0]
    assert synthesized_text == "Opening Spotify."


def test_speak_still_respells_french_text(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_voice = _fake_piper(monkeypatch)

    tts.speak("Je lance Spotify.", language="fr")

    synthesized_text = fake_voice.synthesize_wav.call_args.args[0]
    assert "spo-ti-fa" in synthesized_text.lower()


def test_speak_defaults_to_french_when_language_is_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backward compatible: every caller that predates round 34 does not
    pass `language` at all."""
    fake_voice = _fake_piper(monkeypatch)

    tts.speak("Je lance Spotify.")

    assert tts.DEFAULT_VOICE_NAME in tts._voices
    assert tts.ENGLISH_VOICE_NAME not in tts._voices


def test_speak_caches_french_and_english_voices_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_piper(monkeypatch)

    tts.speak("Bonjour.", language="fr")
    tts.speak("Hello.", language="en")

    assert set(tts._voices) == {tts.DEFAULT_VOICE_NAME, tts.ENGLISH_VOICE_NAME}
