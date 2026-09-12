"""The timer jingle - see `heypeer/tray/alarm_sound.py`."""

import numpy as np

from heypeer.tray import alarm_sound


def _samples(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32767


def test_it_produces_audible_audio() -> None:
    samples = _samples(alarm_sound.render())
    assert len(samples) > alarm_sound.SAMPLE_RATE * 0.5
    assert samples.max() > 0.1


def test_it_never_clips() -> None:
    """It plays over whatever the user is listening to; a clipped tone is
    harsh rather than loud."""
    samples = _samples(alarm_sound.render(repeats=3))
    assert samples.max() < 1.0
    assert samples.min() > -1.0


def test_repeating_lengthens_the_buffer() -> None:
    """How the alarm keeps sounding without a player loop around it."""
    once = len(alarm_sound.render(1))
    twice = len(alarm_sound.render(2))
    assert twice > once * 1.8


def test_zero_repeats_still_produces_one_pass() -> None:
    """A silent alarm is worse than a short one."""
    assert len(alarm_sound.render(0)) > 0


def test_notes_start_and_end_at_silence() -> None:
    """A sine that starts at non-zero amplitude is a step in the waveform,
    and a step is an audible click."""
    samples = _samples(alarm_sound.render())
    assert abs(samples[0]) < 0.01
    assert abs(samples[-1]) < 0.01


def test_the_envelope_is_zero_at_both_ends() -> None:
    total = 1000
    assert alarm_sound._envelope(0, total) == 0.0
    assert alarm_sound._envelope(total, total) < 0.01


def test_it_is_a_chord_not_a_single_beep() -> None:
    """Three rising notes read as "a thing finished"; one tone reads as a
    generic alert."""
    assert len(alarm_sound.NOTES) == 3
    assert list(alarm_sound.NOTES) == sorted(alarm_sound.NOTES)
