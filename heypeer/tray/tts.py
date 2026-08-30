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
# come out clipped and monotone. More variation in phoneme duration is the
# standard way to make Piper sound less mechanical — `noise_w_scale` in
# particular drives prosodic variation, which is most of what "robotic"
# means here.
#
# `length_scale` is speaking rate (higher = slower). It was briefly set to
# 1.06 on the theory that slowing down sounds more natural; the user
# reported the result as simply slow, so it is back to slightly *faster*
# than default. These are short confirmations, not narration — being brisk
# matters more than being deliberate.
SYNTHESIS_LENGTH_SCALE = 0.95
SYNTHESIS_NOISE_SCALE = 0.70
SYNTHESIS_NOISE_W_SCALE = 0.90

# Anything quieter than this fraction of the utterance's peak counts as
# silence for trimming, with a little padding kept so speech isn't clipped.
SILENCE_TRIM_RATIO = 0.02
SILENCE_TRIM_PADDING_SECONDS = 0.03
TRIM_ASSUMED_RATE = 22050  # Piper medium voices' sample rate

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
    """Loads the voice, warms up PortAudio, and synthesises one throwaway
    phrase — all the one-off costs that would otherwise land on the first
    thing Hey Peer says, which is exactly when the user is waiting."""
    import io
    import wave

    from piper.config import SynthesisConfig

    from heypeer.tray import audio_out

    voice = _get_voice()
    audio_out.warm_up()
    try:
        with wave.open(io.BytesIO(), "wb") as sink:
            voice.synthesize_wav("Bonjour.", sink, syn_config=SynthesisConfig())
    except Exception:
        pass  # a warm-up failure must not stop the real thing from working


def speak(text: str) -> None:
    """Synthesizes `text` and plays it back through the default output
    device. Blocks until playback finishes — callers that don't want to wait
    should run this in their own thread."""
    import io
    import wave

    from piper.config import SynthesisConfig

    from heypeer.tray import audio_out

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
        frame_count = wav_file.getnframes()
        raw = wav_file.readframes(frame_count)
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()
        rate = wav_file.getframerate()

    raw = _trim_silence(raw, sample_width)
    audio_out.play(raw, rate=rate, sample_width=sample_width, channels=channels)


def _trim_silence(raw: bytes, sample_width: int) -> bytes:
    """Drops near-silent lead-in and tail from synthesized audio.

    Piper pads every utterance with a couple of hundred milliseconds of
    silence at each end. Playing it makes short confirmations feel sluggish
    — the delay is heard as Hey Peer being slow to answer, and then slow to
    finish — even though the speech itself is a normal length.
    """
    if sample_width != 2:
        return raw  # only int16 is produced here; anything else passes through

    import numpy as np

    samples = np.frombuffer(raw, dtype=np.int16)
    if samples.size == 0:
        return raw
    loud = np.nonzero(np.abs(samples) > np.abs(samples).max() * SILENCE_TRIM_RATIO)[0]
    if loud.size == 0:
        return raw
    keep = int(SILENCE_TRIM_PADDING_SECONDS * TRIM_ASSUMED_RATE)
    start = max(0, loud[0] - keep)
    end = min(samples.size, loud[-1] + keep)
    return samples[start:end].tobytes()
