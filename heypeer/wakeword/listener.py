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
from openwakeword.utils import AudioFeatures

SAMPLE_RATE = 16000
CLIP_SECONDS = 1.5
CHUNK_SAMPLES = 1280  # 80ms chunks, openWakeWord's standard streaming granularity


class WakeWordListener:
    """Listens to the microphone and calls `on_detected` when "Hey Peer" is heard."""

    def __init__(self, model_path: str, threshold: float = 0.5) -> None:
        self.model_path = model_path
        self.threshold = threshold
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
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
        )
        try:
            while self._running:
                raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
                chunk = np.frombuffer(raw, dtype=np.int16)
                if self.process_chunk(chunk) >= self.threshold:
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
