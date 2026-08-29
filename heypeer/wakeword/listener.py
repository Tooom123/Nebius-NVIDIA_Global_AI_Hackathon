"""Real-time "Hey Peer" wake-word detection.

Runs entirely on-device: audio never leaves the machine unless the classifier
fires above `threshold`. Uses the same openWakeWord melspectrogram + embedding
pipeline as `train.py`, feeding a rolling window of the last `CLIP_SECONDS` of
microphone audio into the custom classifier head produced by that script.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import onnxruntime as ort
import openwakeword
from openwakeword.utils import AudioFeatures

SAMPLE_RATE = 16000
CLIP_SECONDS = 1.5
CHUNK_SAMPLES = 1280  # 80ms chunks, openWakeWord's standard streaming granularity


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
        "[wakeword] Modèles openWakeWord manquants (melspectrogram/embedding) — "
        "téléchargement en cours..."
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
        self._buffer = np.zeros(int(CLIP_SECONDS * SAMPLE_RATE), dtype=np.int16)
        self._running = False

    def _score(self) -> float:
        embedding = self._features.embed_clips(
            self._buffer[np.newaxis, :], batch_size=1
        ).mean(axis=1)
        probs = self._session.run(None, {self._input_name: embedding.astype(np.float32)})[1]
        return float(probs[0][1])

    def process_chunk(self, chunk: np.ndarray) -> float:
        """Feed one int16 PCM chunk; returns the current detection score."""
        self._buffer = np.concatenate([self._buffer, chunk])[-len(self._buffer) :]
        return self._score()

    def start(self, on_detected: Callable[[], None]) -> None:
        import pyaudio

        self._running = True
        pa = pyaudio.PyAudio()
        if self.debug:
            try:
                info = pa.get_default_input_device_info()
                print(
                    f"[wakeword] Périphérique d'entrée : {info['name']} "
                    f"(index {info['index']}, {int(info['defaultSampleRate'])} Hz natif)"
                )
            except Exception as exc:  # no default input device, permissions, etc.
                print(f"[wakeword] Impossible de lire le périphérique d'entrée par défaut : {exc}")

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
        )
        if self.debug:
            print(f"[wakeword] Écoute démarrée (seuil de détection = {self.threshold}).")
        try:
            while self._running:
                raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
                chunk = np.frombuffer(raw, dtype=np.int16)
                score = self.process_chunk(chunk)
                if self.debug:
                    dbfs = chunk_dbfs(chunk)
                    bar_len = max(0, min(40, int((dbfs + 60) / 60 * 40)))
                    print(
                        f"\r[wakeword] {dbfs:6.1f} dBFS |{'#' * bar_len:<40}| "
                        f"score={score:.2f}   ",
                        end="",
                        flush=True,
                    )
                if score >= self.threshold:
                    if self.debug:
                        print()  # move off the overwritten debug line
                    print(f"[wakeword] Mot d'activation détecté (score={score:.2f}).")
                    on_detected()
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def stop(self) -> None:
        self._running = False


def default_model_path() -> Path:
    """Path to the trained "Hey Peer" model, once `train.py` has produced one."""
    return Path(__file__).resolve().parent.parent.parent / "data" / "wakeword" / "hey_peer.onnx"
