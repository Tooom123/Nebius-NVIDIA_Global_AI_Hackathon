import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from heypeer.wakeword.listener import (
    CHUNK_SAMPLES,
    INSTRUCTION_SILENCE_CHUNKS,
    SPEECH_THRESHOLD_MAX_DBFS,
    SPEECH_THRESHOLD_MIN_DBFS,
    CHIME_PATH,
    WakeWordListener,
    _ensure_openwakeword_models,
    chunk_dbfs,
    dbfs_to_level,
    estimate_noise_floor,
    play_activation_chime,
    save_wav,
    speech_threshold_dbfs,
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


def test_start_never_triggers_while_muted(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """While muted (a turn is being handled), `start()`'s loop must never
    trigger, so Hey Peer's own TTS or background chatter can't start a
    second turn on top of the first.

    It *does* keep the feature buffer moving, on silence — see the muted
    branch in `start`. Skipping the update entirely left the buffer holding
    the wake word that had just fired, which stopped the listener re-arming
    and made chaining two commands impossible."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)  # anything would trigger if scored
    listener.mute()
    on_detected = MagicMock()

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

    listener.start(on_detected=on_detected)

    on_detected.assert_not_called()


def test_play_chime_goes_through_the_shared_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Playback shares one PortAudio instance; constructing a new one per
    chime and per spoken line was a few hundred ms of device enumeration
    each time, heard as the voice arriving late."""
    from heypeer.wakeword.listener import SAMPLE_RATE, _play_chime_blocking

    play_mock = MagicMock()
    monkeypatch.setattr("heypeer.tray.audio_out.play", play_mock)

    _play_chime_blocking()

    play_mock.assert_called_once()
    assert play_mock.call_args.kwargs["rate"] == SAMPLE_RATE
    assert len(play_mock.call_args.args[0]) > 0


def test_play_activation_chime_does_not_block_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: blocking here delayed the start of instruction
    recording by the chime's length, dropping the first moments of what the
    user said when they ran the wake word straight into the instruction."""
    started = threading.Event()
    release = threading.Event()

    def slow_playback() -> None:
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr("heypeer.wakeword.listener._play_chime_blocking", slow_playback)

    play_activation_chime()  # must return while playback is still going

    assert started.wait(timeout=2)
    release.set()


def _fake_mic(monkeypatch: pytest.MonkeyPatch, listener: WakeWordListener, chunks: list, stop_after: int):
    """Wires a fake pyaudio whose stream replays `chunks` and stops the
    listener after `stop_after` reads. Returns the stream."""
    fake_stream = _FakeStream(chunks)
    reads = {"n": 0}
    real_read = fake_stream.read

    def counting_read(n, exception_on_overflow=False):
        reads["n"] += 1
        if reads["n"] >= stop_after:
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
    return fake_stream


def test_start_calls_on_verify_with_the_pre_trigger_audio(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """The wake word lives in the audio *before* the trigger, so that's what
    verification has to receive."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)
    listener._prebuffer.extend([_loud_chunk()] * 5)
    _fake_mic(monkeypatch, listener, [_quiet_chunk()], stop_after=2)
    seen = {}

    def verify(pre_audio):
        seen["len"] = len(pre_audio)
        return True

    listener.start(on_detected=MagicMock(), on_verify=verify)

    assert seen["len"] > 0


def test_start_suppresses_detection_when_verification_rejects(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """Regression test: the chime and the on-screen blob used to fire on the
    raw detector trigger, so every false positive surfaced to the user. A
    rejected trigger must produce no callback at all."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)
    listener._prebuffer.extend([_loud_chunk()] * 5)
    _fake_mic(monkeypatch, listener, [_quiet_chunk()], stop_after=2)
    on_detected = MagicMock()

    listener.start(on_detected=on_detected, on_verify=lambda _pre: False)

    on_detected.assert_not_called()


def test_start_treats_a_failing_verifier_as_accepted(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """A broken verifier (missing model, transcription error) must not make
    Hey Peer permanently deaf - it falls back to trusting the detector."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)
    listener._prebuffer.extend([_loud_chunk()] * 5)
    _fake_mic(monkeypatch, listener, [_quiet_chunk()], stop_after=2)
    on_detected = MagicMock()

    def broken(_pre):
        raise RuntimeError("model not loaded")

    listener.start(on_detected=on_detected, on_verify=broken)

    on_detected.assert_called_once()


def test_record_instruction_aborts_when_asked(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model))
    listener._prebuffer.extend([_quiet_chunk()] * 10)
    stream = _FakeStream([_loud_chunk()] * 200)

    audio = listener._record_instruction(stream, should_abort=lambda: True)

    assert len(audio) == 0


def test_speech_threshold_tracks_the_noise_floor() -> None:
    """A quiet room and a noisy one must not share one fixed cutoff — that
    was the bug behind instructions being cut off mid-sentence."""
    quiet = speech_threshold_dbfs(-70.0)
    noisy = speech_threshold_dbfs(-45.0)

    assert quiet < noisy
    for threshold in (quiet, noisy):
        assert SPEECH_THRESHOLD_MIN_DBFS <= threshold <= SPEECH_THRESHOLD_MAX_DBFS


def test_speech_threshold_is_clamped_at_both_extremes() -> None:
    assert speech_threshold_dbfs(-120.0) == SPEECH_THRESHOLD_MIN_DBFS  # muted mic
    assert speech_threshold_dbfs(0.0) == SPEECH_THRESHOLD_MAX_DBFS  # absurdly loud room


def test_estimate_noise_floor_ignores_speech_in_the_window() -> None:
    """A low percentile, not a mean: speech inside the measured window
    would drag a mean upward and desensitize the threshold."""
    mostly_quiet = [_quiet_chunk()] * 8 + [_loud_chunk()] * 2

    floor = estimate_noise_floor(mostly_quiet)

    assert floor < chunk_dbfs(_loud_chunk()) - 20


def test_estimate_noise_floor_handles_empty_input() -> None:
    assert estimate_noise_floor([]) < 0  # must not raise


def test_record_instruction_survives_a_mid_sentence_pause(toy_model: Path) -> None:
    """Regression test for the real bug: "déplace le fichier 4.0." was cut
    off because a natural pause between the filename and the destination hit
    the old ~0.8s trailing-silence cutoff."""
    listener = WakeWordListener(str(toy_model))
    listener._prebuffer.extend([_quiet_chunk()] * 10)  # quiet room
    pause_chunks = 9  # ~0.7s - a natural pause, shorter than the new cutoff
    chunks = (
        [_loud_chunk()] * 6
        + [_quiet_chunk()] * pause_chunks
        + [_loud_chunk()] * 6  # the rest of the sentence
        + [_quiet_chunk()] * 25  # actually finished now
    )
    stream = _FakeStream(chunks)

    audio = listener._record_instruction(stream)

    # Must have kept recording through the pause and captured the second half.
    assert len(audio) > CHUNK_SAMPLES * (6 + pause_chunks + 6)


def test_record_instruction_enforces_a_minimum_duration(toy_model: Path) -> None:
    """The guarantee is about how long it *listens* - a slow start must not
    truncate the instruction. It is not about the length returned, since
    trailing silence is trimmed off before transcription."""
    from heypeer.wakeword.listener import CHUNK_SAMPLES, INSTRUCTION_MIN_SECONDS, SAMPLE_RATE

    listener = WakeWordListener(str(toy_model))
    listener._prebuffer.extend([_quiet_chunk()] * 10)
    stream = _FakeStream([_loud_chunk()] * 4 + [_quiet_chunk()] * 60)
    reads = {"n": 0}
    real_read = stream.read

    def counting_read(n, exception_on_overflow=False):
        reads["n"] += 1
        return real_read(n, exception_on_overflow)

    stream.read = counting_read

    listener._record_instruction(stream)

    min_chunks = int(INSTRUCTION_MIN_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)
    assert reads["n"] >= min_chunks


def test_record_instruction_keeps_everything_it_recorded(toy_model: Path) -> None:
    """Regression test: trimming the trailing quiet before transcription
    truncated real instructions ("Deplace le fichier 15-"). "Quiet" means
    below the speech threshold, and the end of a spoken sentence routinely
    trails off below it while still being speech. The ~0.1s of Whisper time
    that trimming saved is not worth losing words over."""
    listener = WakeWordListener(str(toy_model))
    speech_chunks = 8
    stream = _FakeStream([_loud_chunk()] * speech_chunks + [_quiet_chunk()] * 60)

    audio = listener._record_instruction(stream, noise_floor_dbfs=-60.0)

    # Everything up to the end-pointing decision is handed on, tail included.
    assert len(audio) >= CHUNK_SAMPLES * (speech_chunks + INSTRUCTION_SILENCE_CHUNKS)


def test_noise_floor_is_supplied_by_the_caller(toy_model: Path) -> None:
    """The prebuffer is cleared before recording starts, so measuring the
    floor inside `_record_instruction` always saw an empty buffer and fell
    back to a fixed cutoff — the adaptive threshold never adapted, and a
    speaker quieter than that fixed value had the end of every sentence
    treated as silence."""
    listener = WakeWordListener(str(toy_model))
    assert not listener._prebuffer  # as it is when recording begins

    # A very low floor means a low speech threshold, so quiet speech still
    # counts as speech and end-pointing waits for it.
    quiet_speech = np.full(CHUNK_SAMPLES, 400, dtype=np.int16)
    stream = _FakeStream([quiet_speech] * 30)

    audio = listener._record_instruction(stream, noise_floor_dbfs=-70.0)

    assert len(audio) > CHUNK_SAMPLES * 20  # it kept listening


def test_chime_asset_exists_and_is_loadable() -> None:
    """The chime ships as a pre-decoded wav (see `_load_chime`) — if it went
    missing, activation would silently lose its audible cue."""
    import soundfile as sf

    assert CHIME_PATH.is_file()
    data, sr = sf.read(str(CHIME_PATH), dtype="int16")
    assert sr == 16000
    assert data.ndim == 1  # mono
    assert 0.1 < len(data) / sr < 2.0  # a short cue, not a whole track


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


def test_unmute_rearms_so_a_second_wake_word_works_immediately(toy_model: Path) -> None:
    """Regression test for "je ne peux pas enchaîner": after a turn the
    listener stayed effectively deaf for over a second. Two causes, both
    fixed — the feature buffer still held the wake word that had just fired
    (so the score stayed high and `_maybe_trigger` never re-armed), and the
    cooldown was still running."""
    listener = WakeWordListener(str(toy_model), threshold=0.5)

    assert listener._maybe_trigger(0.9) is True  # first activation
    assert listener._maybe_trigger(0.9) is False  # correctly debounced
    listener.mute()

    listener.unmute()

    assert listener._armed is True
    assert listener._maybe_trigger(0.9) is True  # a second "Hey Peer" lands


def test_muted_loop_keeps_the_feature_buffer_moving(toy_model: Path) -> None:
    """The muted branch feeds silence rather than skipping the update, so the
    audio that triggered the turn is flushed out instead of lingering and
    keeping the score high once unmuted."""
    listener = WakeWordListener(str(toy_model), threshold=0.5)
    loud = _loud_chunk()
    for _ in range(20):
        listener.process_chunk(loud)
    scored_hot = listener._score()

    for _ in range(30):  # what the muted branch does each chunk
        listener.process_chunk(np.zeros(CHUNK_SAMPLES, dtype=np.int16))

    assert listener._score() < scored_hot
