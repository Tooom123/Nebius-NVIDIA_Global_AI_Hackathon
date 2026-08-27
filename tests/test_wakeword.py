from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from heypeer.wakeword.listener import CHUNK_SAMPLES, WakeWordListener
from heypeer.wakeword.train import export_onnx, train

SR = 16000


@pytest.fixture(scope="module")
def toy_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Trains a tiny classifier on synthetic tone-vs-noise clips.

    Stands in for real Piper-generated "Hey Peer" samples, which this sandbox
    can't produce (no Piper voices installed) — the point here is to exercise
    the embed -> train -> export -> runtime-inference pipeline end to end.
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
