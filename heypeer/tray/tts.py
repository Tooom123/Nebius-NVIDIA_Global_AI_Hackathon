"""Lightweight local text-to-speech for Hey Peer's own spoken responses
(confirming an action before executing it, Siri/Alexa-style) via Piper —
already a project dependency for wake-word training data, and specifically
chosen here for being local, fast on CPU, and reasonably natural-sounding
("léger" was an explicit requirement) rather than adding a second, heavier
TTS engine.

Defaults to a French voice since the user speaks French natively and all of
Hey Peer's own spoken confirmations (`heypeer/main.py`) are phrased in
French; Whisper transcription of the user's *own* instructions still
auto-detects English just fine (see `heypeer/wakeword/stt.py`), so English
input still works even though Hey Peer's spoken replies are French-first.

Auto-downloads the voice if it isn't present yet, mirroring
`heypeer/wakeword/listener.py`'s `_ensure_openwakeword_models()`.

Piper has no "high" quality French voice — `medium` is the local ceiling
(checked against the published voice list). Within that, the default here is
`fr_FR-upmc-medium` rather than `fr_FR-siwis-medium`, and the synthesis
parameters are tuned away from the flat defaults, both aimed at sounding
less robotic. **Neither choice could be verified by ear while writing this**,
so both are overridable and the alternatives are listed below rather than
baked in: `HEYPEER_TTS_VOICE` (e.g. `fr_FR-siwis-medium`, `fr_FR-tom-medium`,
`fr_FR-mls-medium`) and `HEYPEER_TTS_SPEAKER` (upmc ships two: 0 = jessica,
1 = pierre).
"""

import os
from pathlib import Path

DEFAULT_VOICE_NAME = os.environ.get("HEYPEER_TTS_VOICE") or "fr_FR-upmc-medium"
DEFAULT_SPEAKER_ID = int(os.environ.get("HEYPEER_TTS_SPEAKER") or 0)
VOICES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "wakeword" / "piper_voices"

# Piper's defaults are length_scale=1.0, noise_scale=0.667, noise_w=0.8, which
# come out clipped and monotone. Speaking slightly slower and allowing more
# variation in phoneme duration is the standard way to make Piper sound less
# mechanical — `noise_w_scale` in particular drives prosodic variation, which
# is most of what "robotic" means here.
SYNTHESIS_LENGTH_SCALE = 1.06
SYNTHESIS_NOISE_SCALE = 0.70
SYNTHESIS_NOISE_W_SCALE = 0.90

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
    config = SynthesisConfig(
        speaker_id=DEFAULT_SPEAKER_ID,
        length_scale=SYNTHESIS_LENGTH_SCALE,
        noise_scale=SYNTHESIS_NOISE_SCALE,
        noise_w_scale=SYNTHESIS_NOISE_W_SCALE,
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=config)
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
