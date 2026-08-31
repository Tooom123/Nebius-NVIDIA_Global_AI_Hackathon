"""Lightweight local text-to-speech for Hey Peer's own spoken responses
(confirming an action before executing it, Siri/Alexa-style) via Piper —
already a project dependency for wake-word training data, and specifically
chosen here for being local, fast on CPU, and reasonably natural-sounding
("léger" was an explicit requirement) rather than adding a second, heavier
TTS engine.

Bilingual: French is the default voice, since the user speaks French most of
the time, but `speak(text, language="en")` switches to an English voice
instead. This exists because Nemotron itself now reports which language it
just wrote `speech`/`question` in (see `nemotron/intent.py`'s `language`
field) - occasionally speaking English was always understood correctly (see
`heypeer/wakeword/stt.py`), but the *reply* used to come back in French
regardless, which read as nonsensical rather than merely accented. Piper's
respelling layer (`pronounce.for_speech`) is French-specific and is skipped
entirely for English text - there is no anglicism to fix when the voice
already is English.

Auto-downloads the voice if it isn't present yet, mirroring
`heypeer/wakeword/listener.py`'s `_ensure_openwakeword_models()`.

Piper has no "high" quality French voice — `medium` is the local ceiling
(re-checked against the published voice list: gilles-low, mls-medium,
mls_1840-low, siwis-low, siwis-medium, tom-medium, upmc-medium). Within that,
the default here is `fr_FR-upmc-medium`, and the synthesis parameters are
tuned away from the flat defaults, both aimed at sounding less robotic.

**Neither choice can be verified by ear from here**, and guessing at it in
prose was not getting anywhere, so there is now a way to decide it properly:

    python -m heypeer.tray.tts --demo

renders the same four lines through every French voice and speaker into
`data/tts_demo/`, to be listened to and chosen between. The choice then goes
in `.env` as `HEYPEER_TTS_VOICE` and `HEYPEER_TTS_SPEAKER` (upmc ships two:
0 = jessica, 1 = pierre).

What Hey Peer says is put through `pronounce.for_speech` first — that is the
half of "the voice is not realistic" which *is* diagnosable from here, and it
was a real defect: a French voice was being handed English phonemes it had
never been trained on every time it said "Spotify".
"""

import os
from pathlib import Path

from heypeer.tray.pronounce import for_speech

DEFAULT_VOICE_NAME = os.environ.get("HEYPEER_TTS_VOICE") or "fr_FR-upmc-medium"
DEFAULT_SPEAKER_ID = int(os.environ.get("HEYPEER_TTS_SPEAKER") or 0)
# en_US-lessac-medium: already present in every environment this project has
# run in (downloaded alongside amy/ryan as wake-word training voices, see
# TODO.md), so English replies work with nothing new to fetch. Not chosen
# for any acoustic reason - like the French default, this has never been
# heard, see `--demo` above for how to actually pick one by ear.
ENGLISH_VOICE_NAME = os.environ.get("HEYPEER_TTS_VOICE_EN") or "en_US-lessac-medium"
ENGLISH_SPEAKER_ID = int(os.environ.get("HEYPEER_TTS_SPEAKER_EN") or 0)
VOICES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "wakeword" / "piper_voices"


def _voice_for(language: "str | None") -> "tuple[str, int]":
    """(voice name, speaker id) for `language` - "en" gets the English
    voice, anything else (None included: an older or malformed answer with
    no language reported) falls back to French, today's existing default."""
    if language == "en":
        return ENGLISH_VOICE_NAME, ENGLISH_SPEAKER_ID
    return DEFAULT_VOICE_NAME, DEFAULT_SPEAKER_ID

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

# Keyed by voice name. It used to be a single global, which quietly returned
# whichever voice was loaded first no matter what was asked for - harmless
# while there was only ever one, wrong the moment `--demo` renders several.
_voices: dict = {}


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
    if voice_name not in _voices:
        from piper import PiperVoice

        model_path = _ensure_voice_downloaded(voice_name)
        _voices[voice_name] = PiperVoice.load(str(model_path))
    return _voices[voice_name]


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


def speak(text: str, language: "str | None" = "fr") -> None:
    """Synthesizes `text` and plays it back through the default output
    device. Blocks until playback finishes — callers that don't want to wait
    should run this in their own thread.

    `language` ("fr", "en", or None meaning "unknown, assume fr") picks the
    voice - see `_voice_for`. Only French text goes through
    `pronounce.for_speech`, which respells anglicisms and spells out file
    extensions: that fixes a French voice reading "Spotify" with English
    phonemes it was never trained on, which is not a problem an English
    voice reading English text has - respelling it anyway would mangle
    ordinary English words for no reason.
    """
    import io
    import wave

    from piper.config import SynthesisConfig

    from heypeer.tray import audio_out

    voice_name, speaker_id = _voice_for(language)
    voice = _get_voice(voice_name)
    config = SynthesisConfig(
        speaker_id=speaker_id,
        length_scale=SYNTHESIS_LENGTH_SCALE,
        noise_scale=SYNTHESIS_NOISE_SCALE,
        noise_w_scale=SYNTHESIS_NOISE_W_SCALE,
    )
    spoken_text = for_speech(text) if language != "en" else text
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(spoken_text, wav_file, syn_config=config)
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


# Every French voice Piper publishes, with how many speakers each ships. Used
# by `--demo` so the choice can be made by ear rather than by reading a name.
FRENCH_VOICES = {
    "fr_FR-upmc-medium": 2,  # 0 = jessica, 1 = pierre
    "fr_FR-siwis-medium": 1,
    "fr_FR-tom-medium": 1,
    "fr_FR-mls-medium": 125,  # only the first few are worth auditioning
    "fr_FR-gilles-low": 1,
}

DEMO_SENTENCES = (
    "Je deplace facture.pdf vers Archives.",
    "J'ouvre Spotify.",
    "Tres bien, et toi ?",
    "Je n'ai pas bien compris, peux-tu repeter ?",
)


def render_to_file(text: str, path, voice_name: str, speaker_id: int = 0) -> None:
    """Synthesises one line to a wav file instead of the speakers.

    The point of writing files rather than playing them is `--demo`: whether a
    voice sounds robotic is not a judgement this code can make, so it renders
    the same lines through every French voice and leaves the choice to whoever
    can actually listen.
    """
    import wave

    from piper.config import SynthesisConfig

    voice = _get_voice(voice_name)
    with wave.open(str(path), "wb") as wav_file:
        voice.synthesize_wav(
            for_speech(text),
            wav_file,
            syn_config=SynthesisConfig(
                speaker_id=speaker_id,
                length_scale=SYNTHESIS_LENGTH_SCALE,
                noise_scale=SYNTHESIS_NOISE_SCALE,
                noise_w_scale=SYNTHESIS_NOISE_W_SCALE,
            ),
        )


def _demo(out_dir: Path, voices: "list[str] | None" = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for voice_name in voices or list(FRENCH_VOICES):
        speakers = min(FRENCH_VOICES.get(voice_name, 1), 2)
        for speaker_id in range(speakers):
            for index, sentence in enumerate(DEMO_SENTENCES):
                path = out_dir / f"{voice_name}-speaker{speaker_id}-{index}.wav"
                try:
                    render_to_file(sentence, path, voice_name, speaker_id)
                except Exception as exc:
                    print(f"[tts] {voice_name} speaker {speaker_id}: {exc}")
                    break
            else:
                print(f"[tts] {voice_name} speaker {speaker_id} -> {out_dir}")
                continue
            break
    print(
        f"\nEcoute les fichiers dans {out_dir}, puis mets ton choix dans .env :\n"
        "  HEYPEER_TTS_VOICE=fr_FR-...\n"
        "  HEYPEER_TTS_SPEAKER=0"
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Audition Hey Peer's French voices.")
    parser.add_argument("--demo", action="store_true", help="render every French voice to wav")
    parser.add_argument("--out", default="data/tts_demo", help="where to write them")
    parser.add_argument("--voice", action="append", help="only this voice (repeatable)")
    parser.add_argument("--say", help="speak one line through the configured voice")
    args = parser.parse_args()

    if args.say:
        speak(args.say)
    else:
        _demo(Path(args.out), args.voice)


if __name__ == "__main__":
    main()
