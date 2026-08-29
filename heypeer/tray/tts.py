"""Lightweight local text-to-speech for Hey Peer's own spoken responses
(confirming an action before executing it, Siri/Alexa-style) via Piper —
already a project dependency for wake-word training data, and specifically
chosen here for being local, fast on CPU, and reasonably natural-sounding
("léger" was an explicit requirement) rather than adding a second, heavier
TTS engine.

Auto-downloads a default voice if none is available yet, mirroring
`heypeer/wakeword/listener.py`'s `_ensure_openwakeword_models()`.
"""

from pathlib import Path

DEFAULT_VOICE_NAME = "en_US-lessac-medium"
VOICES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "wakeword" / "piper_voices"

_voice = None


def _ensure_voice_downloaded(voice_name: str) -> Path:
    model_path = VOICES_DIR / f"{voice_name}.onnx"
    if model_path.exists():
        return model_path

    from piper import download_voices

    print(f"[tts] Voix Piper manquante ({voice_name}) - telechargement en cours...")
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    download_voices.download_voice(voice_name, VOICES_DIR)
    return model_path


def _get_voice(voice_name: str = DEFAULT_VOICE_NAME):
    global _voice
    if _voice is None:
        from piper import PiperVoice

        model_path = _ensure_voice_downloaded(voice_name)
        _voice = PiperVoice.load(str(model_path))
    return _voice


def preload() -> None:
    """Loads the default Piper voice now instead of on first use."""
    _get_voice()


def speak(text: str) -> None:
    """Synthesizes `text` and plays it back through the default output
    device. Blocks until playback finishes — callers that don't want to wait
    should run this in their own thread."""
    import io
    import wave

    import pyaudio
    from piper.config import SynthesisConfig

    voice = _get_voice()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=SynthesisConfig())
    buffer.seek(0)

    with wave.open(buffer, "rb") as wav_file:
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pa.get_format_from_width(wav_file.getsampwidth()),
            channels=wav_file.getnchannels(),
            rate=wav_file.getframerate(),
            output=True,
        )
        try:
            data = wav_file.readframes(1024)
            while data:
                stream.write(data)
                data = wav_file.readframes(1024)
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
