import sys
import types
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
    dbfs_to_level,
    play_activation_chime,
    save_wav,
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


def test_maybe_trigger_fires_once_per_utterance_plateau(toy_model: Path) -> None:
    """Regression test: a real utterance keeps the score above threshold for
    several consecutive chunks (a plateau), not just one -- must fire once,
    not once per chunk in that plateau."""
    listener = WakeWordListener(str(toy_model), threshold=0.5)

    # Simulate a plateau: several consecutive above-threshold scores.
    fires = [listener._maybe_trigger(0.9) for _ in range(5)]
    assert fires == [True, False, False, False, False]

    # Score drops back down (utterance ended) then rises again immediately
    # -- cooldown should still block a second fire this soon.
    listener._maybe_trigger(0.1)
    assert listener._maybe_trigger(0.9) is False

    # After the cooldown window, a genuinely new utterance should fire again.
    listener._last_trigger_time -= 10
    assert listener._maybe_trigger(0.9) is True


def test_maybe_trigger_requires_drop_below_threshold_to_rearm(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model), threshold=0.5)
    listener._maybe_trigger(0.9)
    listener._last_trigger_time -= 10  # clear cooldown

    # Still above threshold without ever dropping below it -- must not
    # re-fire just because the cooldown elapsed.
    assert listener._maybe_trigger(0.9) is False


class _FakeStream:
    """Replays a fixed list of int16 chunks, one per .read() call."""

    def __init__(self, chunks: list[np.ndarray]) -> None:
        self._chunks = chunks
        self._i = 0

    def read(self, _n, exception_on_overflow=False):
        chunk = self._chunks[min(self._i, len(self._chunks) - 1)]
        self._i += 1
        return chunk.tobytes()

    def stop_stream(self) -> None:
        pass

    def close(self) -> None:
        pass


def _loud_chunk() -> np.ndarray:
    return np.full(CHUNK_SAMPLES, 20000, dtype=np.int16)


def _quiet_chunk() -> np.ndarray:
    return np.zeros(CHUNK_SAMPLES, dtype=np.int16)


def test_record_instruction_stops_after_trailing_silence(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model))
    # 4 loud chunks (the spoken instruction) then enough quiet chunks to
    # cross the trailing-silence threshold, then more loud chunks that
    # should never be reached.
    chunks = (
        [_loud_chunk()] * 4
        + [_quiet_chunk()] * 15
        + [_loud_chunk()] * 50
    )
    stream = _FakeStream(chunks)

    audio = listener._record_instruction(stream)

    # Stopped well before exhausting the fake stream's trailing loud chunks.
    assert len(audio) < CHUNK_SAMPLES * 30


def test_dbfs_to_level_is_clamped_to_0_1() -> None:
    assert dbfs_to_level(-120) == 0.0
    assert dbfs_to_level(0) == 1.0
    assert 0.0 < dbfs_to_level(-30) < 1.0


def test_record_instruction_reports_level_with_recording_true(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model))
    chunks = [_loud_chunk()] * 4 + [_quiet_chunk()] * 15
    stream = _FakeStream(chunks)
    levels = []

    listener._record_instruction(stream, on_level=lambda level, recording: levels.append(
        (level, recording)
    ))

    assert len(levels) > 0
    assert all(recording is True for _level, recording in levels)
    assert all(0.0 <= level <= 1.0 for level, _recording in levels)


def test_record_instruction_respects_max_duration_cap(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model))
    stream = _FakeStream([_loud_chunk()])  # never goes quiet

    audio = listener._record_instruction(stream)

    from heypeer.wakeword.listener import INSTRUCTION_MAX_SECONDS, SAMPLE_RATE

    assert len(audio) == int(INSTRUCTION_MAX_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES) * CHUNK_SAMPLES


def test_start_skips_scoring_and_triggering_while_muted(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """While muted (Hey Peer's own TTS is playing - see main.py's `_speak`),
    `start()`'s loop must drain the mic without scoring or triggering, so
    Hey Peer's own voice bleeding into the mic can't be scored or
    false-trigger the wake word."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)  # anything would trigger if scored
    listener.mute()
    process_spy = MagicMock(wraps=listener.process_chunk)
    listener.process_chunk = process_spy

    chunks = [_loud_chunk()] * 3
    fake_stream = _FakeStream(chunks)
    reads = {"n": 0}
    real_read = fake_stream.read

    def counting_read(n, exception_on_overflow=False):
        reads["n"] += 1
        if reads["n"] >= len(chunks):
            listener.stop()
        return real_read(n, exception_on_overflow)

    fake_stream.read = counting_read
    fake_pa = MagicMock()
    fake_pa.open.return_value = fake_stream
    fake_pa.get_default_input_device_info.side_effect = Exception("no input device in this sandbox")
    fake_pyaudio_module = types.ModuleType("pyaudio")
    fake_pyaudio_module.PyAudio = MagicMock(return_value=fake_pa)
    fake_pyaudio_module.paInt16 = 8
    monkeypatch.setitem(sys.modules, "pyaudio", fake_pyaudio_module)

    listener.start(on_detected=MagicMock())

    process_spy.assert_not_called()


def test_play_activation_chime_writes_audio_to_output_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_stream = MagicMock()
    fake_pa = MagicMock()
    fake_pa.open.return_value = fake_stream
    fake_pyaudio_module = types.ModuleType("pyaudio")
    fake_pyaudio_module.PyAudio = MagicMock(return_value=fake_pa)
    fake_pyaudio_module.paInt16 = 8
    monkeypatch.setitem(sys.modules, "pyaudio", fake_pyaudio_module)

    play_activation_chime()

    fake_pa.open.assert_called_once()
    assert fake_pa.open.call_args.kwargs["output"] is True
    fake_stream.write.assert_called_once()
    fake_pa.terminate.assert_called_once()


def test_start_plays_chime_on_trigger_before_recording(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """Regression test: the chime is meant to be an *immediate* audible cue
    that Hey Peer heard the wake word, so it must play before the (possibly
    several-second) instruction recording, not after."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)
    call_order = []
    monkeypatch.setattr(
        "heypeer.wakeword.listener.play_activation_chime",
        lambda: call_order.append("chime"),
    )
    original_record = listener._record_instruction

    def recording_spy(*args, **kwargs):
        call_order.append("record")
        return original_record(*args, **kwargs)

    listener._record_instruction = recording_spy

    chunks = [_loud_chunk()]
    fake_stream = _FakeStream(chunks)
    reads = {"n": 0}
    real_read = fake_stream.read

    def counting_read(n, exception_on_overflow=False):
        reads["n"] += 1
        if reads["n"] >= 2:
            listener.stop()
        return real_read(n, exception_on_overflow)

    fake_stream.read = counting_read
    fake_pa = MagicMock()
    fake_pa.open.return_value = fake_stream
    fake_pa.get_default_input_device_info.side_effect = Exception("no input device in this sandbox")
    fake_pyaudio_module = types.ModuleType("pyaudio")
    fake_pyaudio_module.PyAudio = MagicMock(return_value=fake_pa)
    fake_pyaudio_module.paInt16 = 8
    monkeypatch.setitem(sys.modules, "pyaudio", fake_pyaudio_module)

    listener.start(on_detected=MagicMock())

    assert call_order == ["chime", "record"]


def test_unmute_clears_the_muted_flag(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model))
    listener.mute()
    assert listener._muted is True

    listener.unmute()

    assert listener._muted is False


def test_save_wav_round_trips(tmp_path: Path) -> None:
    audio = (0.5 * np.sin(2 * np.pi * 440 * np.linspace(0, 1, SR)) * 32767).astype(np.int16)
    out_path = tmp_path / "clip.wav"

    save_wav(audio, out_path)

    read_back, sr = sf.read(str(out_path), dtype="int16")
    assert sr == SR
    assert len(read_back) == len(audio)
