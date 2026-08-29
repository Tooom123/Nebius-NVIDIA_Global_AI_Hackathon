"""Real-time "Hey Peer" wake-word detection.

Runs entirely on-device: audio never leaves the machine unless the classifier
fires above `threshold`. Uses the same openWakeWord melspectrogram + embedding
pipeline as `train.py`, feeding a rolling window of the last `CLIP_SECONDS` of
microphone audio into the custom classifier head produced by that script.

Scoring uses `AudioFeatures`'s own incremental streaming API
(`_streaming_features`/`get_features`, exposed via `__call__`) rather than
calling `embed_clips()` on the whole rolling window every chunk. The first
version of this listener did the latter — recomputing the melspectrogram and
embeddings for the entire ~1.5s window on every single 80ms chunk — which is
exactly the "reprocess everything, constantly" pattern real always-listening
wake-word engines (Hey Siri, Alexa, OK Google) specifically avoid. The
streaming API only processes the newest samples each call and keeps a
rolling feature buffer internally, cutting the per-chunk work roughly to the
size of one chunk instead of the size of the whole detection window.
"""

import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import onnxruntime as ort
import openwakeword
from openwakeword.utils import AudioFeatures

SAMPLE_RATE = 16000
CLIP_SECONDS = 1.5
CHUNK_SAMPLES = 1280  # 80ms chunks, openWakeWord's standard streaming granularity
COOLDOWN_SECONDS = 1.5  # minimum gap between two separate detections

# Simple energy-based end-pointing for the instruction recorded right after a
# wake-word trigger — good enough for a spoken command a few seconds long
# without pulling in a separate VAD model.
INSTRUCTION_MAX_SECONDS = 8.0
INSTRUCTION_SILENCE_CHUNKS = 10  # ~0.8s of trailing silence ends the recording
INSTRUCTION_MIN_SPEECH_CHUNKS = 3
SPEECH_DBFS_THRESHOLD = -40.0  # chunks louder than this count as "speech"

# Same end-pointing, tuned shorter for a one-word spoken yes/no confirmation
# reply rather than a full instruction.
CONFIRMATION_MAX_SECONDS = 4.0
CONFIRMATION_SILENCE_CHUNKS = 6  # ~0.5s trailing silence - a short reply needs less patience
CONFIRMATION_MIN_SPEECH_CHUNKS = 2


def _ensure_openwakeword_models() -> None:
    """openWakeWord's melspectrogram/embedding ONNX models are bundled in
    some package versions but not others (0.6.0's wheel is ~60 KB — clearly
    not including them; a version pinned only as ">=0.4.0" can land either
    way depending on when/where `pip install` runs). Rather than pin an
    exact version and hope, check for the files openWakeWord itself expects
    by default and download them on the spot if missing — this is exactly
    what surfaced as a raw onnxruntime NoSuchFile traceback on a fresh
    Windows install after this project's own AudioFeatures() call.
    """
    models_dir = Path(openwakeword.__file__).parent / "resources" / "models"
    required = [models_dir / "melspectrogram.onnx", models_dir / "embedding_model.onnx"]
    if all(p.exists() for p in required):
        return

    from openwakeword.utils import download_models

    print(
        "[wakeword] Modeles openWakeWord manquants (melspectrogram/embedding) - "
        "telechargement en cours..."
    )
    # A model name that matches nothing skips downloading the large bundle of
    # official pretrained wake words (alexa, hey_jarvis, ...) we don't use —
    # download_models() unconditionally fetches melspec/embedding/VAD first
    # regardless of model_names, which is all we actually need here.
    download_models(model_names=["__heypeer_placeholder_no_match__"])


def chunk_dbfs(chunk: np.ndarray) -> float:
    """RMS level of an int16 PCM chunk in dBFS (0 = full scale, more negative =
    quieter; silence/no signal reads around -90 or lower)."""
    if len(chunk) == 0:
        return -120.0
    rms = np.sqrt(np.mean(chunk.astype(np.float64) ** 2))
    return float(20 * np.log10(rms / 32768 + 1e-9))


def dbfs_to_level(dbfs: float) -> float:
    """Normalizes dBFS to a 0-1 range for the UI's audio-reactive circle
    (same -60..0 dBFS window the console debug meter already uses)."""
    return max(0.0, min(1.0, (dbfs + 60) / 60))


def save_wav(audio: np.ndarray, path) -> None:
    """Writes recorded int16 mono PCM audio to a 16kHz wav file."""
    import soundfile as sf

    sf.write(str(path), audio, SAMPLE_RATE, subtype="PCM_16")


def _record_with_vad(
    stream,
    max_seconds: float,
    silence_chunks: int,
    min_speech_chunks: int,
    on_level: "Callable[[float, bool], None] | None" = None,
) -> np.ndarray:
    """Shared energy-based end-pointing loop behind both `_record_instruction`
    (reuses the wake-word listener's already-open stream) and
    `record_voice_reply` (opens its own short-lived stream) — same idea,
    different timing constants for a full instruction vs. a short yes/no."""
    frames = []
    speech_started = False
    speech_chunks = 0
    quiet_run = 0
    max_chunks = int(max_seconds * SAMPLE_RATE / CHUNK_SAMPLES)
    for _ in range(max_chunks):
        raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
        chunk = np.frombuffer(raw, dtype=np.int16)
        frames.append(chunk)
        dbfs = chunk_dbfs(chunk)
        if on_level is not None:
            on_level(dbfs_to_level(dbfs), True)
        if dbfs > SPEECH_DBFS_THRESHOLD:
            speech_started = True
            speech_chunks += 1
            quiet_run = 0
        elif speech_started:
            quiet_run += 1
        if speech_started and speech_chunks >= min_speech_chunks and quiet_run >= silence_chunks:
            break
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)


def record_voice_reply(on_level: "Callable[[float, bool], None] | None" = None) -> np.ndarray:
    """Records a brief spoken reply (a yes/no confirmation) on its own
    short-lived mic stream. Doesn't reuse the wake-word listener's own
    stream — confirmation is handled on a different thread than the
    continuously-running wake-word audio loop (see main.py's module
    docstring on why `on_detected` only enqueues rather than handling things
    inline), and only needs the mic for a couple of seconds, not
    continuously."""
    import pyaudio

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SAMPLES,
    )
    try:
        return _record_with_vad(
            stream,
            CONFIRMATION_MAX_SECONDS,
            CONFIRMATION_SILENCE_CHUNKS,
            CONFIRMATION_MIN_SPEECH_CHUNKS,
            on_level,
        )
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


class WakeWordListener:
    """Listens to the microphone and calls `on_detected` when "Hey Peer" is heard."""

    def __init__(self, model_path: str, threshold: float = 0.5, debug: bool = False) -> None:
        self.model_path = model_path
        self.threshold = threshold
        # TEMPORARY: prints a live dB meter + score per chunk, and the input
        # device name at startup, so mic hardware issues are obvious instead
        # of "nothing happens, no idea why". Remove/gate more permanently
        # once real wake-word detection is validated on real hardware.
        self.debug = debug
        _ensure_openwakeword_models()
        self._features = AudioFeatures()
        self._session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        # Number of embedding frames that add up to CLIP_SECONDS — matches
        # what train.py's embed_clips()/.mean(axis=1) produced per training
        # clip, so streaming scoring stays consistent with what the
        # classifier actually learned.
        self._n_feature_frames = self._features.get_embedding_shape(CLIP_SECONDS)[0]
        self._running = False
        self._debug_print_counter = 0
        # A single utterance of "Hey Peer" keeps the score above threshold
        # for several consecutive chunks (it's a plateau, not a single
        # spike) -- without debouncing, on_detected() fired once per chunk
        # in that plateau, i.e. several times for one utterance. Only fire
        # on the rising edge (was below, now above), and refuse to fire
        # again within COOLDOWN_SECONDS regardless, as a backstop.
        self._armed = True
        self._last_trigger_time = 0.0

    def _maybe_trigger(self, score: float) -> bool:
        """Returns True at most once per utterance (rising edge + cooldown)."""
        if score < self.threshold:
            self._armed = True
            return False
        if not self._armed:
            return False
        if time.time() - self._last_trigger_time < COOLDOWN_SECONDS:
            return False
        self._armed = False
        self._last_trigger_time = time.time()
        return True

    def _score(self) -> float:
        features = self._features.get_features(n_feature_frames=self._n_feature_frames)
        embedding = features.mean(axis=1)
        probs = self._session.run(None, {self._input_name: embedding.astype(np.float32)})[1]
        return float(probs[0][1])

    def process_chunk(self, chunk: np.ndarray) -> float:
        """Feed one int16 PCM chunk (>= CHUNK_SAMPLES); incrementally updates
        openWakeWord's internal streaming feature buffer and returns the
        current detection score."""
        self._features(chunk)
        return self._score()

    def _record_instruction(
        self, stream, on_level: "Callable[[float, bool], None] | None" = None
    ) -> np.ndarray:
        """Records audio right after a wake-word trigger, on the same open
        mic stream, until the user stops talking or a max-duration safety
        cap is hit. Wake-word scoring is paused for this stretch — it's
        the instruction being captured, not more "Hey Peer"s to detect."""
        return _record_with_vad(
            stream,
            INSTRUCTION_MAX_SECONDS,
            INSTRUCTION_SILENCE_CHUNKS,
            INSTRUCTION_MIN_SPEECH_CHUNKS,
            on_level,
        )

    def start(
        self,
        on_detected: Callable[[np.ndarray], None],
        on_level: "Callable[[float, bool], None] | None" = None,
    ) -> None:
        """`on_level(level, recording)` — level normalized 0-1 (see
        `dbfs_to_level`), `recording` True while capturing the instruction
        after a trigger, False while just scanning for the wake word. Meant
        to drive a live audio-reactive UI element; optional."""
        import pyaudio

        self._running = True
        pa = pyaudio.PyAudio()
        if self.debug:
            try:
                info = pa.get_default_input_device_info()
                print(
                    f"[wakeword] Peripherique d'entree : {info['name']} "
                    f"(index {info['index']}, {int(info['defaultSampleRate'])} Hz natif)"
                )
            except Exception as exc:  # no default input device, permissions, etc.
                print(f"[wakeword] Impossible de lire le peripherique d'entree par defaut : {exc}")

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
        )
        if self.debug:
            print(f"[wakeword] Ecoute demarree (seuil de detection = {self.threshold}).")
        try:
            while self._running:
                raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
                chunk = np.frombuffer(raw, dtype=np.int16)
                score = self.process_chunk(chunk)
                dbfs = chunk_dbfs(chunk)
                if on_level is not None:
                    on_level(dbfs_to_level(dbfs), False)
                if self.debug:
                    # Printing (with a flush) every single 80ms chunk was
                    # measurably heavier on a slow terminal (Git Bash/MinTTY
                    # in particular) than the actual scoring work itself --
                    # every 3rd chunk (~240ms) still reads as live to a human
                    # eye and cuts that console I/O by two thirds.
                    self._debug_print_counter += 1
                    if self._debug_print_counter % 3 == 0:
                        bar_len = max(0, min(40, int(dbfs_to_level(dbfs) * 40)))
                        print(
                            f"\r[wakeword] {dbfs:6.1f} dBFS |{'#' * bar_len:<40}| "
                            f"score={score:.2f}   ",
                            end="",
                            flush=True,
                        )
                if self._maybe_trigger(score):
                    if self.debug:
                        print()  # move off the overwritten debug line
                    print(f"[wakeword] Mot d'activation detecte (score={score:.2f}).")
                    instruction_audio = self._record_instruction(stream, on_level=on_level)
                    print(
                        f"[wakeword] Instruction enregistree "
                        f"({len(instruction_audio) / SAMPLE_RATE:.1f}s)."
                    )
                    on_detected(instruction_audio)
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def stop(self) -> None:
        self._running = False


def default_model_path() -> Path:
    """Path to the trained "Hey Peer" model, once `train.py` has produced one."""
    return Path(__file__).resolve().parent.parent.parent / "data" / "wakeword" / "hey_peer.onnx"
