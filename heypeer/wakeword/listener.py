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

import threading
import time
from collections import deque
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
# ~1.2s of trailing silence ends the recording. Was ~0.8s, which cut real
# instructions off mid-sentence on the user's hardware ("déplace le fichier
# 4.0.", "Déplace le fichier 4.txt-"): people pause naturally between a
# filename and a destination, and that pause was being read as "done".
INSTRUCTION_SILENCE_CHUNKS = 15
INSTRUCTION_MIN_SPEECH_CHUNKS = 3
# Never end-point before this much audio, regardless of silence — protects
# against a slow start (a breath, a pause for thought) truncating the whole
# instruction to nothing.
INSTRUCTION_MIN_SECONDS = 1.2

# Speech is detected relative to the room's own noise floor rather than at a
# fixed level. A fixed -40 dBFS threshold assumes one particular mic gain and
# room: too high and a quiet speaker never registers, too low and every fan
# or keyboard click counts as speech. `SPEECH_MARGIN_DB` above the measured
# floor is what actually separates "someone is talking" from "the room".
SPEECH_MARGIN_DB = 12.0
# Bounds keep the adaptive threshold sane if calibration lands somewhere odd
# (a muted mic reads ~-90 dBFS; a very loud room could otherwise push the
# threshold above normal speech).
SPEECH_THRESHOLD_MIN_DBFS = -55.0
SPEECH_THRESHOLD_MAX_DBFS = -25.0
# Fallback for the very first detection, before any noise floor is measured.
SPEECH_DBFS_THRESHOLD = -40.0


def speech_threshold_dbfs(noise_floor_dbfs: float) -> float:
    """Speech/silence cutoff for a room whose measured noise floor is
    `noise_floor_dbfs`, clamped to a sane range."""
    return max(
        SPEECH_THRESHOLD_MIN_DBFS,
        min(SPEECH_THRESHOLD_MAX_DBFS, noise_floor_dbfs + SPEECH_MARGIN_DB),
    )


def estimate_noise_floor(chunks: "list[np.ndarray]") -> float:
    """Estimates the ambient noise floor from recent audio, as the 20th
    percentile of per-chunk levels — a low percentile rather than the
    minimum (robust to one freak-quiet chunk) and rather than the mean
    (which speech in the same window would drag upward)."""
    if not chunks:
        return SPEECH_DBFS_THRESHOLD - SPEECH_MARGIN_DB
    levels = [chunk_dbfs(c) for c in chunks]
    return float(np.percentile(levels, 20))

# How much audio from *before* a trigger to keep and hand to the verifier.
# Detection fires at the end of the spoken phrase, so the wake word lives
# entirely in this window — 2s covers "Hey Peer" plus lead-in comfortably.
PREBUFFER_SECONDS = 2.0
PREBUFFER_CHUNKS = int(PREBUFFER_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

# Upper bound on waiting for `on_verify` once recording has finished. It
# normally completes long before this (it starts at the same moment and only
# has ~2s of audio to transcribe); the cap just guarantees the listener can
# never wedge on a stuck verifier.
VERIFY_TIMEOUT_SECONDS = 6.0


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


CHIME_PATH = Path(__file__).resolve().parent.parent / "assets" / "activation_chime.wav"

_chime_audio: "np.ndarray | None" = None


def _load_chime() -> np.ndarray:
    """Loads (and caches) the activation chime. Shipped as a pre-decoded
    16kHz mono WAV rather than the original mp3 the user supplied: decoding
    mp3 needs libsndfile >= 1.1, which isn't guaranteed on every install,
    and this keeps playback on the same int16/pyaudio path as the rest of
    the audio pipeline."""
    global _chime_audio
    if _chime_audio is None:
        import soundfile as sf

        data, _sr = sf.read(str(CHIME_PATH), dtype="int16")
        _chime_audio = data if data.ndim == 1 else data.mean(axis=1).astype(np.int16)
    return _chime_audio


def play_activation_chime() -> None:
    """Plays the activation chime the instant the wake word triggers. The
    user reported not being sure whether Hey Peer had actually heard them; a
    near-instant audible cue (far faster than speaking a full sentence via
    Piper) gives that confirmation the same way real voice assistants do.

    Plays on its own thread so it does **not** delay the start of instruction
    recording: people run the wake word straight into the instruction ("Hey
    Peer, déplace le fichier..."), and blocking here for the chime's duration
    would drop the first fraction of a second of what they said. The chime
    does bleed into the mic as a result, which is harmless — it's a short
    tone at the very start, and Whisper's VAD skips non-speech anyway.
    """
    threading.Thread(target=_play_chime_blocking, daemon=True).start()


def _play_chime_blocking() -> None:
    import pyaudio

    audio = _load_chime()
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, output=True)
    try:
        stream.write(audio.tobytes())
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
        # Muted while Hey Peer's own TTS is speaking (see main.py's `_speak`)
        # so its own voice bleeding back into the mic — a real issue with
        # some headsets — can't be scored or false-trigger the wake word.
        # Not true acoustic echo cancellation (no cancellation happens *during*
        # simultaneous playback+speech), but Hey Peer never needs to listen
        # for the wake word while it's actively talking anyway, so gating
        # fully covers the "hears itself" symptom this was meant to fix.
        self._muted = False
        # Rolling window of the most recent raw chunks, so the audio that
        # *caused* a detection (the wake word itself) can be handed to the
        # second-stage verifier along with the instruction — see
        # heypeer/wakeword/verify.py. Detection fires at the end of the
        # phrase, so without this the wake word is already gone by the time
        # recording starts.
        self._prebuffer: deque = deque(maxlen=PREBUFFER_CHUNKS)

    def mute(self) -> None:
        self._muted = True

    def unmute(self) -> None:
        """Re-arms as well as unmuting, so a new "Hey Peer" can follow
        immediately after a turn. Without the explicit re-arm the listener
        waited for the score to fall below the threshold on its own, which
        made chaining two commands feel broken."""
        self._muted = False
        self._armed = True
        self._last_trigger_time = 0.0
        self._prebuffer.clear()

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
        self,
        stream,
        on_level: "Callable[[float, bool], None] | None" = None,
        should_abort: "Callable[[], bool] | None" = None,
    ) -> np.ndarray:
        """Records audio right after a wake-word trigger, on the same open
        mic stream, until the user stops talking or a max-duration safety
        cap is hit. Wake-word scoring is paused for this stretch — it's
        the instruction being captured, not more "Hey Peer"s to detect.

        End-pointing reads the level relative to the room's own noise floor
        (measured from the prebuffer, which is real audio from the seconds
        just before the user started speaking) rather than a fixed dBFS
        cutoff — see `speech_threshold_dbfs`."""
        threshold = speech_threshold_dbfs(estimate_noise_floor(list(self._prebuffer)))
        frames = []
        speech_started = False
        speech_chunks = 0
        quiet_run = 0
        max_chunks = int(INSTRUCTION_MAX_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)
        min_chunks = int(INSTRUCTION_MIN_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)
        for i in range(max_chunks):
            if should_abort is not None and should_abort():
                # Verification (running concurrently on the prebuffer) has
                # ruled this out as a false trigger - stop recording rather
                # than hold the mic for several more seconds for nothing.
                return np.zeros(0, dtype=np.int16)
            raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            chunk = np.frombuffer(raw, dtype=np.int16)
            frames.append(chunk)
            dbfs = chunk_dbfs(chunk)
            if on_level is not None:
                on_level(dbfs_to_level(dbfs), True)
            if dbfs > threshold:
                speech_started = True
                speech_chunks += 1
                quiet_run = 0
            elif speech_started:
                quiet_run += 1
            if (
                i + 1 >= min_chunks
                and speech_started
                and speech_chunks >= INSTRUCTION_MIN_SPEECH_CHUNKS
                and quiet_run >= INSTRUCTION_SILENCE_CHUNKS
            ):
                break
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)

    def start(
        self,
        on_detected: Callable[[np.ndarray], None],
        on_level: "Callable[[float, bool], None] | None" = None,
        on_verify: "Callable[[np.ndarray], bool] | None" = None,
    ) -> None:
        """`on_level(level, recording)` — level normalized 0-1 (see
        `dbfs_to_level`), `recording` True while capturing the instruction
        after a trigger, False while just scanning for the wake word. Meant
        to drive a live audio-reactive UI element; optional.

        `on_verify(pre_trigger_audio)` decides whether a detection was real,
        given the ~2s of audio containing the wake word itself. It runs on
        its own thread while the instruction is being recorded, and is where
        any user-visible reaction to a detection belongs (chime, indicator)
        — the raw detector fires on plenty of ordinary speech, so reacting
        before this confirms would surface every false positive. Returning
        False aborts the in-progress recording and suppresses `on_detected`.
        Optional; without it every trigger is treated as genuine."""
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
                if self._muted:
                    # Keep the streaming feature buffer moving, on silence
                    # rather than on the real (muted) audio. Skipping the
                    # update entirely — which is what this used to do — left
                    # the buffer holding the wake word that just fired: on
                    # unmute it still scored high, so `_maybe_trigger` never
                    # re-armed and a second "Hey Peer" was ignored for over a
                    # second. Feeding silence flushes it, so Hey Peer is ready
                    # again the moment the turn ends.
                    self.process_chunk(np.zeros(CHUNK_SAMPLES, dtype=np.int16))
                    continue
                chunk = np.frombuffer(raw, dtype=np.int16)
                self._prebuffer.append(chunk)
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
                        print(f"[wakeword] Candidat detecte (score={score:.2f}).")
                    # The prebuffer already holds the wake word (detection
                    # fires at the end of the phrase), so it can be verified
                    # right now — before any chime or on-screen reaction.
                    pre_audio = (
                        np.concatenate(list(self._prebuffer))
                        if self._prebuffer
                        else np.zeros(0, dtype=np.int16)
                    )
                    self._prebuffer.clear()

                    # Verification runs *concurrently* with recording rather
                    # than before it. Doing it first would be simpler, but it
                    # takes a few hundred ms, and that would be a hole in the
                    # captured audio for anyone who runs the wake word
                    # straight into the instruction — which is how people
                    # actually talk ("Hey Peer, déplace le fichier...").
                    verdict: dict = {"ok": None}

                    def _verify() -> None:
                        try:
                            verdict["ok"] = (
                                on_verify(pre_audio) if on_verify is not None else True
                            )
                        except Exception:
                            verdict["ok"] = True  # never lose a real activation to a bug

                    verifier = threading.Thread(target=_verify, daemon=True)
                    verifier.start()

                    instruction_audio = self._record_instruction(
                        stream,
                        on_level=on_level,
                        should_abort=lambda: verdict["ok"] is False,
                    )
                    verifier.join(timeout=VERIFY_TIMEOUT_SECONDS)

                    if verdict["ok"] is False:
                        if self.debug:
                            print("[wakeword] Rejete (pas de mot d'activation).")
                        continue
                    print(
                        f"[wakeword] Instruction enregistree "
                        f"({len(instruction_audio) / SAMPLE_RATE:.1f}s)."
                    )
                    on_detected(np.concatenate([pre_audio, instruction_audio]))
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def stop(self) -> None:
        self._running = False


def default_model_path() -> Path:
    """Path to the trained "Hey Peer" model, once `train.py` has produced one."""
    return Path(__file__).resolve().parent.parent.parent / "data" / "wakeword" / "hey_peer.onnx"
