from unittest.mock import MagicMock

import numpy as np
import pytest

import heypeer.wakeword.stt as stt


@pytest.fixture(autouse=True)
def reset_model_cache():
    stt._models.clear()
    yield
    stt._models.clear()


def test_transcribe_empty_audio_returns_empty_string_without_loading_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_mock = MagicMock()
    monkeypatch.setattr(stt, "_get_model", load_mock)

    result = stt.transcribe(np.zeros(0, dtype=np.int16))

    assert result == ""
    load_mock.assert_not_called()


def test_transcribe_joins_segment_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = MagicMock()
    segment1, segment2 = MagicMock(text=" hello "), MagicMock(text="world ")
    fake_model.transcribe.return_value = ([segment1, segment2], MagicMock())
    monkeypatch.setattr(stt, "_get_model", lambda *_a, **_k: fake_model)

    result = stt.transcribe(np.ones(1600, dtype=np.int16))

    assert result == "hello world"


def test_get_model_caches_per_model_name(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_whisper_model_cls = MagicMock(side_effect=lambda *a, **k: MagicMock())
    fake_module = MagicMock(WhisperModel=fake_whisper_model_cls)
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", fake_module)

    first = stt._get_model("small")
    second = stt._get_model("small")
    other = stt._get_model("base")

    assert first is second
    assert other is not first
    assert fake_whisper_model_cls.call_count == 2


def test_verification_uses_a_faster_model_than_instructions() -> None:
    """The verify model runs before the activation chime, so its latency is
    felt directly; the instruction model is the one that has to get
    filenames right. They are deliberately not the same."""
    assert stt.VERIFY_MODEL != stt.INSTRUCTION_MODEL
    assert stt.INSTRUCTION_MODEL == "small"
    assert stt.VERIFY_MODEL == "base"


def test_transcribe_defaults_to_the_instruction_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_get_model(name):
        seen["name"] = name
        model = MagicMock()
        model.transcribe.return_value = ([], MagicMock())
        return model

    monkeypatch.setattr(stt, "_get_model", fake_get_model)

    stt.transcribe(np.ones(1600, dtype=np.int16))

    assert seen["name"] == stt.INSTRUCTION_MODEL


def test_transcribe_enables_vad_filter_and_prompt_bias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: vad_filter targets Whisper hallucinating whole
    sentences over background noise/silence with no real speech in it."""
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([], MagicMock())
    monkeypatch.setattr(stt, "_get_model", lambda *_a, **_k: fake_model)

    stt.transcribe(np.ones(1600, dtype=np.int16))

    call_kwargs = fake_model.transcribe.call_args.kwargs
    assert call_kwargs["vad_filter"] is True
    assert call_kwargs["initial_prompt"] == stt.INITIAL_PROMPT


def test_transcribe_can_disable_vad_for_short_clips(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a ~2s wake-word clip the VAD filter often discards everything,
    which made verification reject real activations."""
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([], MagicMock())
    monkeypatch.setattr(stt, "_get_model", lambda *_a, **_k: fake_model)

    stt.transcribe(np.ones(1600, dtype=np.int16), use_vad=False)

    assert fake_model.transcribe.call_args.kwargs["vad_filter"] is False


def test_preload_loads_both_models(monkeypatch: pytest.MonkeyPatch) -> None:
    get_model_mock = MagicMock()
    monkeypatch.setattr(stt, "_get_model", get_model_mock)

    stt.preload()

    loaded = {call.args[0] for call in get_model_mock.call_args_list}
    assert loaded == {stt.VERIFY_MODEL, stt.INSTRUCTION_MODEL}
