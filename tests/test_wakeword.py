import sys
import threading
import types
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from heypeer.wakeword.listener import (
    CHUNK_SAMPLES,
    PRIMING_CHUNKS,
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
    listener after `stop_after` reads *of the real detection loop*.

    `start()` now reads `PRIMING_CHUNKS` of real audio to prime the feature
    buffer (round 32, see `_prime_feature_buffer`) before that loop begins,
    and those reads go through this same fake stream - so the threshold is
    offset by `PRIMING_CHUNKS` to keep every existing caller's `stop_after`
    meaning what it always meant, without editing each one.
    """
    fake_stream = _FakeStream(chunks)
    reads = {"n": 0}
    real_read = fake_stream.read

    def counting_read(n, exception_on_overflow=False):
        reads["n"] += 1
        if reads["n"] >= PRIMING_CHUNKS + stop_after:
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


def test_start_treats_a_failing_verifier_as_accepted(  # noqa: D401
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


def test_recording_starts_only_after_the_indicator_has_appeared(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """Regression test: verification used to run *alongside* recording, so the
    chime and the blob only appeared once recording was well under way - the
    user had usually finished speaking by the time the blob arrived, and it
    never seemed to react to their voice. Cue first, then listen."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)
    listener._prebuffer.extend([_loud_chunk()] * 5)
    order = []

    def verify(_pre):
        order.append("cue")
        return True

    original_record = listener._record_instruction

    def record(*args, **kwargs):
        order.append("record")
        return original_record(*args, **kwargs)

    listener._record_instruction = record
    _fake_mic(monkeypatch, listener, [_quiet_chunk()], stop_after=2)

    listener.start(on_detected=MagicMock(), on_verify=verify)

    assert order == ["cue", "record"]


def test_a_rejected_trigger_never_records(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    listener = WakeWordListener(str(toy_model), threshold=0.0)
    listener._prebuffer.extend([_loud_chunk()] * 5)
    listener._record_instruction = MagicMock()
    _fake_mic(monkeypatch, listener, [_quiet_chunk()], stop_after=2)

    listener.start(on_detected=MagicMock(), on_verify=lambda _pre: False)

    listener._record_instruction.assert_not_called()


def test_on_ready_fires_after_the_delay_and_before_recording(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """The chime is the "speak now" cue, so it has to land once the indicator
    has arrived and finish before the mic opens - otherwise the beep is the
    first thing the recording contains."""
    listener = WakeWordListener(str(toy_model), threshold=0.0)
    listener._prebuffer.extend([_loud_chunk()] * 5)
    order = []
    original_record = listener._record_instruction

    def record(*args, **kwargs):
        order.append("record")
        return original_record(*args, **kwargs)

    listener._record_instruction = record
    _fake_mic(monkeypatch, listener, [_quiet_chunk()], stop_after=2)

    listener.start(
        on_detected=MagicMock(),
        on_verify=lambda _pre: (order.append("show"), True)[1],
        on_ready=lambda: order.append("chime"),
    )

    assert order == ["show", "chime", "record"]


def test_the_chime_is_short_enough_to_precede_recording() -> None:
    """It is played synchronously now, so its length is dead time before the
    user may speak."""
    import soundfile as sf

    audio, sr = sf.read(str(CHIME_PATH), dtype="int16")

    assert len(audio) / sr < 0.4


def test_play_activation_chime_can_block(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "heypeer.wakeword.listener._play_chime_blocking", lambda: calls.append("played")
    )

    play_activation_chime(blocking=True)

    assert calls == ["played"]  # already done by the time it returns


# --- Cold-start feature buffer priming (round 32) -------------------------
#
# Distinct from round 25's "the first Hey Peer was answered several seconds
# late" (that was Whisper's *verifier* model still loading). This is the
# detector itself scoring low on the very first utterance, because
# openWakeWord seeds its feature buffer from ten seconds of synthetic
# silence at construction time - see `_prime_feature_buffer`'s docstring for
# the exact mechanism, quoted straight from openwakeword's own source.


def test_priming_reads_real_audio_and_never_scores_or_calls_back(
    toy_model: Path,
) -> None:
    """`_prime_feature_buffer` must consume exactly `PRIMING_CHUNKS` of real
    stream reads (not fewer - that would leave the seed unflushed - and not
    more, which would eat into audio a caller expects `start()` to still
    process) and must never fire a detection: at this point the buffer is
    not trustworthy yet, so nothing scored against it should be acted on.
    """
    listener = WakeWordListener(str(toy_model), threshold=0.0)  # would trigger on anything scored
    listener._running = True  # normally set by start(); priming checks it to stay stoppable
    tone_chunk = (
        0.3 * np.sin(2 * np.pi * 310 * np.linspace(0, 0.08, CHUNK_SAMPLES)) * 32767
    ).astype(np.int16)
    stream = _FakeStream([tone_chunk] * PRIMING_CHUNKS)

    listener._prime_feature_buffer(stream)

    assert stream._i == PRIMING_CHUNKS


def test_start_calls_priming_on_the_real_stream_before_the_loop(
    monkeypatch: pytest.MonkeyPatch, toy_model: Path
) -> None:
    """Wiring test: proves `start()` actually calls `_prime_feature_buffer`
    on its real code path, not just that the helper exists somewhere unused
    - this project has shipped that exact "wired up but never written" gap
    before (round 27's `_on_ready_to_listen`).

    Patching the method directly, rather than inferring the call from its
    side effects, avoids a wrong assumption an earlier draft of this test
    made: priming does not *suppress* detection of audio that happens to
    fall inside its window, it only defers scoring it until the window
    closes - a "Hey Peer" spoken the instant listening starts is still
    caught, just up to `PRIMING_CHUNKS` chunks later, once real scoring
    resumes and the (now real-audio-filled) buffer is looked at for the
    first time. That is actually the fix working as intended, not a
    loophole - but it makes on_detected the wrong signal for "was priming
    called", since firing late still looks like firing.
    """
    listener = WakeWordListener(str(toy_model))
    fake_stream = _FakeStream([_quiet_chunk()])
    reads = {"n": 0}
    real_read = fake_stream.read

    def counting_read(n, exception_on_overflow=False):
        reads["n"] += 1
        if reads["n"] >= 3:
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

    with mock.patch.object(
        WakeWordListener, "_prime_feature_buffer", autospec=True
    ) as prime:
        listener.start(on_detected=MagicMock())

    prime.assert_called_once_with(listener, fake_stream)


def test_mute_except_barge_in_keeps_scoring_but_stays_muted(toy_model: Path) -> None:
    """Barge-in listening is a *third* state, not just unmuted: turn-taking
    must stay off (the mic is picking up Hey Peer's own voice) while the
    wake word is still scored so it can interrupt."""
    listener = WakeWordListener(str(toy_model), threshold=0.5)

    listener.mute_except_barge_in()
    assert listener._muted is True
    assert listener._listen_for_barge_in is True


def test_plain_mute_does_not_listen_for_barge_in(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model), threshold=0.5)
    listener.mute_except_barge_in()
    listener.mute()
    assert listener._listen_for_barge_in is False


def test_unmute_clears_barge_in_listening(toy_model: Path) -> None:
    """Otherwise an ordinary turn would keep firing the interrupt callback."""
    listener = WakeWordListener(str(toy_model), threshold=0.5)
    listener.mute_except_barge_in()
    listener.unmute()
    assert listener._muted is False
    assert listener._listen_for_barge_in is False


def test_on_barge_in_defaults_to_nothing_to_interrupt(toy_model: Path) -> None:
    listener = WakeWordListener(str(toy_model), threshold=0.5)
    assert listener.on_barge_in is None


def test_a_short_utterance_that_trailed_off_ends_the_turn_quickly() -> None:
    """"annule" - short, and fading at the end - is finished, and making the
    user wait 1.2s for Hey Peer to notice is what reads as sluggish."""
    from heypeer.wakeword.listener import (
        INSTRUCTION_SILENCE_CHUNKS_MIN,
        silence_chunks_needed,
    )

    assert silence_chunks_needed(4, trailing_off=True) == INSTRUCTION_SILENCE_CHUNKS_MIN


def test_a_long_utterance_gets_the_patient_wait() -> None:
    """Regression guard for the original truncation bug: "deplace le fichier
    facture de mars" pausing before "vers Archives" must not be cut off."""
    from heypeer.wakeword.listener import (
        INSTRUCTION_SILENCE_CHUNKS_MAX,
        LONG_UTTERANCE_CHUNKS,
        silence_chunks_needed,
    )

    assert (
        silence_chunks_needed(LONG_UTTERANCE_CHUNKS, trailing_off=True)
        == INSTRUCTION_SILENCE_CHUNKS_MAX
    )
    assert (
        silence_chunks_needed(LONG_UTTERANCE_CHUNKS + 5, trailing_off=False)
        == INSTRUCTION_SILENCE_CHUNKS_MAX
    )


def test_an_ambiguous_pause_keeps_the_old_behaviour() -> None:
    """Short but holding level - could be either. The two failures are not
    symmetric (truncating loses what was said), so ambiguity keeps the
    patient default rather than gambling on the fast one."""
    from heypeer.wakeword.listener import INSTRUCTION_SILENCE_CHUNKS, silence_chunks_needed

    assert silence_chunks_needed(4, trailing_off=False) == INSTRUCTION_SILENCE_CHUNKS


def test_the_adaptive_wait_never_leaves_its_bounds() -> None:
    from heypeer.wakeword.listener import (
        INSTRUCTION_SILENCE_CHUNKS_MAX,
        INSTRUCTION_SILENCE_CHUNKS_MIN,
        silence_chunks_needed,
    )

    for burst in range(0, 40):
        for trailing in (True, False):
            needed = silence_chunks_needed(burst, trailing)
            assert INSTRUCTION_SILENCE_CHUNKS_MIN <= needed <= INSTRUCTION_SILENCE_CHUNKS_MAX


def test_the_fast_path_is_never_slower_than_the_old_fixed_wait() -> None:
    """The point of the feature: it can only ever end a turn sooner than
    before, never later than the previous ceiling."""
    from heypeer.wakeword.listener import (
        INSTRUCTION_SILENCE_CHUNKS_MAX,
        silence_chunks_needed,
    )

    assert silence_chunks_needed(2, True) <= INSTRUCTION_SILENCE_CHUNKS_MAX


class _ScriptedStream:
    """Replays a scripted list of per-chunk levels as real PCM, so
    `_record_instruction`'s actual loop can be driven without a microphone."""

    def __init__(self, dbfs_sequence: "list[float]") -> None:
        self._sequence = list(dbfs_sequence)
        self.reads = 0

    def read(self, n, exception_on_overflow=False):
        from heypeer.wakeword.listener import CHUNK_SAMPLES

        dbfs = self._sequence[self.reads] if self.reads < len(self._sequence) else -90.0
        self.reads += 1
        amplitude = (10 ** (dbfs / 20)) * 32768
        rng = np.random.default_rng(self.reads)
        chunk = (rng.standard_normal(CHUNK_SAMPLES) * amplitude).astype(np.int16)
        return chunk.tobytes()


def test_recording_stops_sooner_after_a_short_fading_utterance(toy_model: Path) -> None:
    """End to end through the real loop, not just the decision function."""
    from heypeer.wakeword.listener import INSTRUCTION_SILENCE_CHUNKS

    listener = WakeWordListener(str(toy_model))
    # A short burst that fades, then silence.
    speech = [-20.0, -22.0, -26.0, -32.0]
    stream = _ScriptedStream(speech + [-90.0] * 40)
    listener._record_instruction(stream, noise_floor_dbfs=-60.0)
    # Old behaviour would have read at least min_seconds' worth plus the full
    # fixed silence run; the fast path must beat that.
    assert stream.reads < len(speech) + INSTRUCTION_SILENCE_CHUNKS + 15


def test_a_pause_mid_sentence_does_not_truncate_the_instruction(toy_model: Path) -> None:
    """The original bug: "deplace le fichier 4.0." cut off at the pause.
    The second half must still make it into the recording."""
    listener = WakeWordListener(str(toy_model))
    first_half = [-20.0] * 14          # long burst, holding level
    pause = [-90.0] * 12               # ~1s pause, under the patient threshold
    second_half = [-20.0] * 6
    stream = _ScriptedStream(first_half + pause + second_half + [-90.0] * 40)
    audio = listener._record_instruction(stream, noise_floor_dbfs=-60.0)
    from heypeer.wakeword.listener import CHUNK_SAMPLES

    chunks_recorded = len(audio) // CHUNK_SAMPLES
    assert chunks_recorded > len(first_half) + len(pause), "cut off at the pause"
