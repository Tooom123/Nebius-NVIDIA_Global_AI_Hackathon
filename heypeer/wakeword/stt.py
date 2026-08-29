"""Local speech-to-text for the instruction spoken right after "Hey Peer".

Nemotron 3 Nano Omni is multimodal in principle, but the Nebius Token
Factory deployment this project talks to rejects every audio content-part
shape tried (`input_audio`, `audio_url`, `audio` — all OpenAI/vLLM
conventions) with an identical 422 the moment the content list contains
anything other than `text`/`image_url`: there is no audio-input support on
this endpoint today, confirmed by testing directly against the real API,
not by reading docs. `NemotronClient.interpret()` is left in place in case
that changes, but nothing calls it anymore.

Transcribing locally with Whisper (via `faster-whisper`, CPU, int8) and
sending the resulting text — plus a screenshot — to
`NemotronClient.interpret_text()` keeps the actual reasoning/intent
extraction on Nemotron while working around the missing audio input.

Bumped from "base" to "small" and given a French-biased `initial_prompt`,
plus `vad_filter=True`, after real transcripts on real hardware showed two
distinct problems: garbled short words (filenames especially — "4.xt"/
"4.tx" instead of "4.txt", "des places" instead of "déplace") and outright
hallucinated sentences over background noise/silence with no real speech in
them at all ("Il est gigant d'habille, putain." — a textbook Whisper
hallucination-on-silence artifact, not a mistranscription of anything
actually said). `vad_filter=True` runs faster-whisper's built-in Silero VAD
first and skips non-speech stretches instead of transcribing them, which
specifically targets the second problem; "small" (vs "base") and the prompt
bias target the first. Loading the model still takes several seconds -
`preload()` is meant to be called once at startup rather than paying that
cost on the user's first spoken instruction; the "small" model itself still
transcribes a several-second clip well under a second on CPU once loaded.

Auto-detects language (tested working for English and French) rather than
forcing one — `initial_prompt` biases vocabulary/style without forcing the
decoder to assume a specific spoken language, so a French-biased prompt
still shouldn't hurt English recognition.
"""

import numpy as np

_model = None

MODEL_NAME = "small"

# Nudges the decoder toward the vocabulary Hey Peer's instructions actually
# use, without forcing a language — helps most on short phrases and
# filenames/extensions, which are otherwise easy for Whisper to garble.
INITIAL_PROMPT = (
    "Hey Peer. Déplace, renomme, crée ou supprime un fichier ou un dossier. "
    "Fais-en encore quelques-uns de plus."
)


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def preload() -> None:
    """Loads the Whisper model now instead of on first use, so the user's
    first spoken instruction isn't delayed by a several-second model load."""
    _get_model()


def transcribe(audio: np.ndarray) -> str:
    """Transcribes int16 mono 16kHz PCM audio to text. Returns "" for
    empty/silent input rather than calling the model on nothing."""
    if len(audio) == 0:
        return ""
    audio_float = audio.astype(np.float32) / 32768.0
    model = _get_model()
    segments, _info = model.transcribe(
        audio_float, language=None, vad_filter=True, initial_prompt=INITIAL_PROMPT
    )
    return " ".join(segment.text.strip() for segment in segments).strip()
