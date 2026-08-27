"""Real-time "Hey Peer" wake-word detection on top of openWakeWord.

Training pipeline (Piper TTS sample generation + openWakeWord training) lands in a
later step; this module only defines the runtime listener interface.
"""

from collections.abc import Callable


class WakeWordListener:
    """Listens to the microphone and calls `on_detected` when "Hey Peer" is heard."""

    def __init__(self, model_path: str, threshold: float = 0.5) -> None:
        self.model_path = model_path
        self.threshold = threshold

    def start(self, on_detected: Callable[[], None]) -> None:
        raise NotImplementedError("Wake-word runtime listener not implemented yet")

    def stop(self) -> None:
        raise NotImplementedError("Wake-word runtime listener not implemented yet")
