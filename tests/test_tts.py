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
    tts._voice = None
    yield
    tts._voice = None


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
