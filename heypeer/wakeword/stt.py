"""Local speech-to-text for the instruction spoken right after "Hey Peer".

Nemotron 3 Nano Omni is multimodal in principle, but the Nebius Token
Factory deployment this project talks to rejects every audio content-part
shape tried (`input_audio`, `audio_url`, `audio` — all OpenAI/vLLM
conventions) with an identical 422 the moment the content list contains
anything other than `text`/`image_url`: there is no audio-input support on
this endpoint today, confirmed by testing directly against the real API,
not by reading docs. `NemotronClient.interpret()` is left in place in case
that changes, but nothing calls it anymore.

Transcribing locally with a small Whisper model (via `faster-whisper`, CPU,
int8) and sending the resulting text — plus a screenshot — to
`NemotronClient.interpret_text()` keeps the actual reasoning/intent
extraction on Nemotron while working around the missing audio input.
`faster-whisper`'s "base" model auto-detects language (tested working for
English and French) and transcribes a several-second clip in well under a
second on CPU once loaded; loading it takes several seconds, so `preload()`
is meant to be called once at startup rather than paying that cost on the
user's first spoken instruction.
"""

import numpy as np

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel("base", device="cpu", compute_type="int8")
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
    segments, _info = model.transcribe(audio_float, language=None)
    return " ".join(segment.text.strip() for segment in segments).strip()
