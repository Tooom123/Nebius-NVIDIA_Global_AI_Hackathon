from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from heypeer.wakeword.listener import (
    CHUNK_SAMPLES,
    WakeWordListener,
    _ensure_openwakeword_models,
    chunk_dbfs,
)
from heypeer.wakeword.train import export_onnx, train

SR = 16000


@pytest.fixture(scope="module")
def toy_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Trains a tiny classifier on synthetic tone-vs-noise clips.

    A real "Hey Peer" model (trained on real Piper-synthesized speech) is
    also produced by this pipeline now (see generate_samples.py/train.py) —
    this fixture just keeps the unit test itself fast and self-contained.
    """
    root = tmp_path_factory.mktemp("wakeword_fixture")
    pos_dir, neg_dir = root / "positive", root / "negative"
    pos_dir.mkdir()
    neg_dir.mkdir()

    rng = np.random.default_rng(0)
    for i in range(10):
        t = np.linspace(0, 1.5, int(1.5 * SR), endpoint=False)
        tone = (0.3 * np.sin(2 * np.pi * (300 + i * 5) * t) * 32767).astype("int16")
        sf.write(pos_dir / f"p{i}.wav", tone, SR)
    for i in range(10):
        noise = (0.1 * rng.standard_normal(int(1.5 * SR)) * 32767).astype("int16")
        sf.write(neg_dir / f"n{i}.wav", noise, SR)

    clf, input_dim = train(pos_dir, neg_dir)
    model_path = root / "model.onnx"
    export_onnx(clf, input_dim, model_path)
    return model_path


def test_process_chunk_scores_positive_tone_higher(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model))

    tone_chunk = (
        0.3 * np.sin(2 * np.pi * 310 * np.linspace(0, 0.08, CHUNK_SAMPLES)) * 32767
    ).astype(np.int16)
    for _ in range(20):
        tone_score = listener.process_chunk(tone_chunk)

    rng = np.random.default_rng(1)
    noise_chunk = (0.1 * rng.standard_normal(CHUNK_SAMPLES) * 32767).astype(np.int16)
    for _ in range(20):
        noise_score = listener.process_chunk(noise_chunk)

    assert tone_score > noise_score


def test_chunk_dbfs_silence_is_much_quieter_than_full_scale() -> None:
    silence = np.zeros(CHUNK_SAMPLES, dtype=np.int16)
    full_scale = np.full(CHUNK_SAMPLES, 32767, dtype=np.int16)

    assert chunk_dbfs(silence) < -80
    assert chunk_dbfs(full_scale) > -1


def test_chunk_dbfs_empty_chunk_does_not_crash() -> None:
    assert chunk_dbfs(np.array([], dtype=np.int16)) < 0


def test_ensure_openwakeword_models_skips_download_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Path(fake_openwakeword.__file__).parent / "resources" / "models" is
    # where _ensure_openwakeword_models looks for the required files.
    pkg_dir = tmp_path / "pkg"
    (pkg_dir / "resources" / "models").mkdir(parents=True)
    (pkg_dir / "resources" / "models" / "melspectrogram.onnx").write_bytes(b"x")
    (pkg_dir / "resources" / "models" / "embedding_model.onnx").write_bytes(b"x")
    fake_openwakeword = MagicMock(__file__=str(pkg_dir / "__init__.py"))
    monkeypatch.setattr("heypeer.wakeword.listener.openwakeword", fake_openwakeword)

    download_mock = MagicMock()
    monkeypatch.setattr("openwakeword.utils.download_models", download_mock, raising=False)

    _ensure_openwakeword_models()

    download_mock.assert_not_called()


def test_ensure_openwakeword_models_downloads_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    fake_openwakeword = MagicMock(__file__=str(pkg_dir / "__init__.py"))
    monkeypatch.setattr("heypeer.wakeword.listener.openwakeword", fake_openwakeword)

    download_mock = MagicMock()
    monkeypatch.setattr("openwakeword.utils.download_models", download_mock, raising=False)

    _ensure_openwakeword_models()

    download_mock.assert_called_once()
