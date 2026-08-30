"""Tests for the voice-sample recorder.

The interactive parts need a microphone, but the decisions that affect data
quality — rejecting a silent take, retrying it, writing the right files — are
pure logic and tested here against a fake stream.
"""

from pathlib import Path

import numpy as np
import pytest

from heypeer.wakeword import record_samples


class _FakeStream:
    """Replays a fixed list of int16 chunks, one per `read`."""

    def __init__(self, chunks: "list[np.ndarray]") -> None:
        self._chunks = chunks
        self._i = 0

    def read(self, n, exception_on_overflow=False):
        chunk = self._chunks[min(self._i, len(self._chunks) - 1)]
        self._i += 1
        return chunk.tobytes()


def _loud(n: int = record_samples.CHUNK) -> np.ndarray:
    return np.full(n, 12000, dtype=np.int16)


def _silent(n: int = record_samples.CHUNK) -> np.ndarray:
    return np.zeros(n, dtype=np.int16)


@pytest.fixture(autouse=True)
def no_countdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """The countdown sleeps for real seconds; tests shouldn't."""
    monkeypatch.setattr(record_samples, "_countdown", lambda _label, _seconds: None)


def test_record_clip_returns_the_requested_duration() -> None:
    stream = _FakeStream([_loud()])

    clip = record_samples.record_clip(stream, seconds=2.0)

    expected = int(record_samples.SAMPLE_RATE * 2.0 / record_samples.CHUNK)
    assert len(clip) == expected * record_samples.CHUNK


def test_silent_takes_are_rejected() -> None:
    """A silent clip saved as a positive would teach the model that silence
    is the wake word — worse than simply having one fewer sample."""
    assert record_samples.is_usable(_silent(16000)) is False
    assert record_samples.is_usable(_loud(16000)) is True


def test_clip_peak_is_a_fraction_of_full_scale() -> None:
    assert record_samples.clip_peak(np.zeros(10, dtype=np.int16)) == 0.0
    assert record_samples.clip_peak(np.full(10, 32767, dtype=np.int16)) == pytest.approx(1.0, abs=0.01)
    assert record_samples.clip_peak(np.zeros(0, dtype=np.int16)) == 0.0


def test_record_set_writes_one_file_per_prompt(tmp_path: Path) -> None:
    stream = _FakeStream([_loud()])

    saved = record_samples.record_set(
        stream, tmp_path, ["Hey Peer", "Hey Peer", "Hey Peer"], seconds=0.5, prefix="pos"
    )

    assert saved == 3
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == [
        "pos_000.wav", "pos_001.wav", "pos_002.wav"
    ]


def test_record_set_retries_a_silent_take(tmp_path: Path) -> None:
    """The prompt is repeated until something is actually captured, rather
    than silently banking a dead clip."""
    chunks_per_clip = int(record_samples.SAMPLE_RATE * 0.5 / record_samples.CHUNK)
    stream = _FakeStream([_silent()] * chunks_per_clip + [_loud()])

    saved = record_samples.record_set(stream, tmp_path, ["Hey Peer"], seconds=0.5, prefix="pos")

    assert saved == 1
    assert len(list(tmp_path.glob("*.wav"))) == 1


def test_saved_clips_are_16khz_mono(tmp_path: Path) -> None:
    """Training rejects anything else outright."""
    import soundfile as sf

    stream = _FakeStream([_loud()])
    record_samples.record_set(stream, tmp_path, ["Hey Peer"], seconds=0.5, prefix="pos")

    audio, sr = sf.read(str(next(tmp_path.glob("*.wav"))), dtype="int16")
    assert sr == record_samples.SAMPLE_RATE
    assert audio.ndim == 1


def test_negative_prompts_cover_the_three_kinds_that_matter() -> None:
    """Near-misses, the real commands (the detector was seen firing partway
    through one), and ordinary speech. Positives alone would let the model
    separate the classes on voice identity instead of on content."""
    prompts = [p.lower() for p in record_samples.NEGATIVE_PROMPTS]

    assert any("pierre" in p for p in prompts)  # near-miss
    assert any("déplace" in p for p in prompts)  # a real command
    assert any("annule" in p for p in prompts)
    assert len(prompts) >= 20
