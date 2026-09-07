"""Kokoro English speech - see `heypeer/tray/kokoro_tts.py`.

Driven against a fake pipeline: what matters here is the routing and the
degradation, not torch's output. Whether the voice actually sounds good was
settled by ear, on real Hey Peer lines.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from conftest import _fake_piper
from heypeer.tray import kokoro_tts, tts


def _fake_kokoro(monkeypatch, chunks=None):
    """A stand-in Kokoro pipeline yielding `chunks` of float32 audio."""
    audio = chunks if chunks is not None else [np.zeros(2400, dtype=np.float32)]
    pipeline = MagicMock(return_value=[(None, None, c) for c in audio])
    monkeypatch.setattr(kokoro_tts, "_get_pipeline", lambda: pipeline)
    monkeypatch.setattr(kokoro_tts, "is_available", lambda: True)
    return pipeline


def test_synthesize_returns_int16_pcm(monkeypatch) -> None:
    """audio_out plays int16; Kokoro emits float32 in -1..1."""
    _fake_kokoro(monkeypatch, [np.full(100, 0.5, dtype=np.float32)])
    raw = kokoro_tts.synthesize("Hello.")
    assert raw is not None
    samples = np.frombuffer(raw, dtype="<i2")
    assert len(samples) == 100
    assert 16000 < samples[0] < 17000  # 0.5 * 32767


def test_clipping_is_bounded_not_wrapped(monkeypatch) -> None:
    """An out-of-range sample must clamp, not overflow into loud noise."""
    _fake_kokoro(monkeypatch, [np.full(10, 3.0, dtype=np.float32)])
    samples = np.frombuffer(kokoro_tts.synthesize("Hello."), dtype="<i2")
    assert samples.max() == 32767


def test_multiple_chunks_are_joined(monkeypatch) -> None:
    _fake_kokoro(monkeypatch, [np.zeros(100, dtype=np.float32)] * 3)
    samples = np.frombuffer(kokoro_tts.synthesize("A longer sentence."), dtype="<i2")
    assert len(samples) == 300


def test_it_uses_the_chosen_voice(monkeypatch) -> None:
    pipeline = _fake_kokoro(monkeypatch)
    kokoro_tts.synthesize("Hello.")
    assert pipeline.call_args.kwargs["voice"] == kokoro_tts.DEFAULT_ENGLISH_VOICE


def test_the_default_voice_is_the_one_chosen_by_ear() -> None:
    """af_bella: graded A- on the largest corpus, and measurably faster
    than af_heart. Picked by the user from real Hey Peer lines."""
    assert kokoro_tts.DEFAULT_ENGLISH_VOICE == "af_bella"


def test_unavailable_returns_none_rather_than_raising(monkeypatch) -> None:
    """The caller's fallback is Piper; it must not need a try/except."""
    monkeypatch.setattr(kokoro_tts, "is_available", lambda: False)
    assert kokoro_tts.synthesize("Hello.") is None


def test_a_synthesis_failure_returns_none(monkeypatch) -> None:
    """espeak-ng missing, a model load failure - all the same to the caller."""
    monkeypatch.setattr(kokoro_tts, "is_available", lambda: True)
    monkeypatch.setattr(
        kokoro_tts, "_get_pipeline",
        lambda: (_ for _ in ()).throw(RuntimeError("no espeak-ng")),
    )
    assert kokoro_tts.synthesize("Hello.") is None


def test_empty_output_returns_none(monkeypatch) -> None:
    _fake_kokoro(monkeypatch, [])
    assert kokoro_tts.synthesize("") is None


def test_preload_is_safe_when_kokoro_is_absent(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_tts, "is_available", lambda: False)
    assert kokoro_tts.preload() is False


# --- routing, in tts.speak ---

def test_english_goes_through_kokoro(monkeypatch) -> None:
    _fake_piper(monkeypatch)
    called = {}

    def fake_synth(text, *a, **k):
        called["text"] = text
        return b"\x00\x00" * 100

    monkeypatch.setattr("heypeer.tray.kokoro_tts.synthesize", fake_synth)
    play = MagicMock()
    monkeypatch.setattr("heypeer.tray.audio_out.play", play)

    tts.speak("Moving invoice.pdf to Archives.", language="en")

    assert called["text"] == "Moving invoice.pdf to Archives."
    assert play.call_args.kwargs["rate"] == kokoro_tts.SAMPLE_RATE


def test_french_never_goes_through_kokoro(monkeypatch) -> None:
    """Kokoro's one French voice is trained on the same SIWIS corpus Piper
    already has, at real latency cost - French must stay on Piper."""
    fake_voice = _fake_piper(monkeypatch)
    kokoro = MagicMock()
    monkeypatch.setattr("heypeer.tray.kokoro_tts.synthesize", kokoro)

    tts.speak("Bonjour.", language="fr")

    kokoro.assert_not_called()
    fake_voice.synthesize_wav.assert_called_once()


def test_no_language_is_treated_as_french(monkeypatch) -> None:
    """A malformed or pre-language-aware answer must not silently switch
    engines."""
    _fake_piper(monkeypatch)
    kokoro = MagicMock()
    monkeypatch.setattr("heypeer.tray.kokoro_tts.synthesize", kokoro)

    tts.speak("Bonjour.", language=None)

    kokoro.assert_not_called()


def test_a_kokoro_failure_falls_back_to_piper(monkeypatch) -> None:
    """A worse-sounding answer beats a silent one."""
    fake_voice = _fake_piper(monkeypatch)
    monkeypatch.setattr("heypeer.tray.kokoro_tts.synthesize", lambda *a, **k: None)

    tts.speak("Opening Spotify.", language="en")

    fake_voice.synthesize_wav.assert_called_once()
