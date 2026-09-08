"""English speech through Kokoro, the better-sounding of the two engines.

## Why a second engine rather than replacing Piper

They are good at different languages, and the difference is not close.
Measured and listened to, not assumed:

* **English.** Kokoro's `af_bella` is graded A- on 100-1000 hours of
  training data, `af_heart` A. Piper's English voices sound synthetic
  beside them - the user's verdict on real Hey Peer lines was that only the
  Kokoro female voices were credible.
* **French.** Kokoro publishes exactly one French voice, `ff_siwis`, graded
  B- on under 11 hours - and it is trained on the *same SIWIS corpus* that
  Piper's `fr_FR-siwis-medium` already uses. There is no new voice to gain,
  only a different vocoder over the same source.

So English goes through Kokoro and French stays on Piper. That is not a
compromise pending a better model; it is where each engine is actually
strongest today.

## What it costs

Kokoro is a 82M-parameter torch model against Piper's small ONNX one, and
that shows up as latency. Measured here on CPU, three short lines:

    Piper  en_US-lessac-medium   0.15s   (RTF 0.03)
    Kokoro af_bella              0.92s   (RTF 0.12)
    Kokoro af_heart              1.65s   (RTF 0.24)

`af_bella` is both the better-graded voice and the faster one, which is why
it is the default.

Those numbers include a cold model load. Measured again *after* `preload()`,
the same sentence synthesises in 0.06s - RTF 0.02, faster than Piper. So
the entire cost is the one-off ~7.6s load, which `preload()` pays at
startup alongside Piper's and PortAudio's, and steady-state English speech
is free. The French measurement was RTF 0.61 warm, which is the other
reason French stays on Piper.

## Optional, like every other heavy dependency here

`kokoro` and `torch` are not in requirements.txt - they are a large install
for one language's voice. `is_available()` reports honestly and `tts.speak`
falls back to Piper's English voice, so a machine without them is a
slightly worse-sounding Hey Peer rather than a broken one. Same shape as
`executor/system_audio.py` and the two agent modules.

Kokoro also needs the `espeak-ng` binary for grapheme-to-phoneme; its
absence surfaces as an exception at synthesis time, which the fallback in
`tts.speak` already covers.
"""

import os

# af_bella: graded A- with the largest training corpus Kokoro publishes,
# and measurably faster than af_heart (0.92s vs 1.65s for the same three
# lines). Chosen by the user by ear from real Hey Peer sentences, not from
# the grades alone. Override with HEYPEER_KOKORO_VOICE.
DEFAULT_ENGLISH_VOICE = os.environ.get("HEYPEER_KOKORO_VOICE") or "af_bella"

# Kokoro's own output rate. Piper medium voices are 22050; audio_out is told
# the rate per call, so the two engines coexist without resampling.
SAMPLE_RATE = 24000

_pipeline = None


def is_available() -> bool:
    """Whether Kokoro can be used at all. Checked rather than assumed at
    every call site: not installing a torch-sized dependency is an ordinary
    choice, not an error state."""
    try:
        import kokoro  # noqa: F401
    except ImportError:
        return False
    return True


def _get_pipeline():
    """The process-wide Kokoro pipeline, built on first use.

    `lang_code='a'` is American English. Kokoro keys voices to a pipeline's
    language, so a French voice would need a second pipeline - deliberately
    not built, see the module docstring for why French stays on Piper.
    """
    global _pipeline
    if _pipeline is None:
        from kokoro import KPipeline

        _pipeline = KPipeline(lang_code="a")
    return _pipeline


def synthesize(text: str, voice: str = "") -> "bytes | None":
    """`text` as raw 16-bit mono PCM at `SAMPLE_RATE`, or None if Kokoro
    cannot produce it.

    Returning None rather than raising: the caller's fallback is to say the
    same sentence through Piper, which is a better outcome than an
    exception, and it must not need a try/except to get there.
    """
    if not is_available():
        return None
    try:
        import numpy as np

        pipeline = _get_pipeline()
        chunks = [
            np.asarray(audio)
            for _, _, audio in pipeline(text, voice=voice or DEFAULT_ENGLISH_VOICE)
        ]
    except Exception:
        return None
    if not chunks:
        return None
    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    # Kokoro returns float32 in -1..1; audio_out plays int16 PCM.
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def preload() -> bool:
    """Builds the pipeline and synthesises one throwaway phrase, so the
    ~7.6s model load does not land on the first thing Hey Peer says.

    Returns whether it worked. Called from `tts.preload`, which already does
    the same for Piper and PortAudio.
    """
    if not is_available():
        return False

    # Kokoro's grapheme-to-phoneme layer (misaki) uses spaCy, and downloads
    # en_core_web_sm the first time it runs - 12MB, once, installed as a
    # package. Harmless, and alarming to watch happen unannounced in the
    # middle of a launch: the user reported exactly that as an error. Saying
    # what is about to happen costs one line and turns it into progress.
    try:
        import spacy

        if not spacy.util.is_package("en_core_web_sm"):
            print("[tts] Premier lancement : telechargement du modele de prononciation (12 Mo)...")
    except Exception:
        pass  # spaCy absent or changed - the download either happens quietly or not at all

    try:
        return synthesize("Ready.") is not None
    except Exception:
        return False
