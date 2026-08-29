from unittest.mock import MagicMock

import numpy as np
import pytest

import heypeer.wakeword.stt as stt


@pytest.fixture(autouse=True)
def reset_model_cache():
    stt._model = None
    yield
    stt._model = None


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
    monkeypatch.setattr(stt, "_get_model", lambda: fake_model)

    result = stt.transcribe(np.ones(1600, dtype=np.int16))

    assert result == "hello world"


def test_get_model_caches_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_whisper_model_cls = MagicMock()
    fake_module = MagicMock(WhisperModel=fake_whisper_model_cls)
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", fake_module)

    first = stt._get_model()
    second = stt._get_model()

    assert first is second
    fake_whisper_model_cls.assert_called_once()


def test_preload_calls_get_model(monkeypatch: pytest.MonkeyPatch) -> None:
    get_model_mock = MagicMock()
    monkeypatch.setattr(stt, "_get_model", get_model_mock)

    stt.preload()

    get_model_mock.assert_called_once()
