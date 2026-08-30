"""Tests for how training clips are turned into fixed-length windows.

Both behaviours here were found by reproducing a real failure: a model
trained on the user's own recordings scored 1.00 on *everything*, including
pure silence, so no threshold separated anything.
"""

import numpy as np
import pytest

from heypeer.wakeword.train import (
    TARGET_SR,
    _loudest_window,
    _silence_and_noise_clips,
    _sliding_windows,
)


def test_loudest_window_finds_speech_that_starts_late() -> None:
    """After a countdown people begin a few hundred ms in. Keeping the first
    slice cut the wake word out of its own training clip and kept the silence
    in front of it."""
    audio = np.zeros(2 * TARGET_SR, dtype=np.int16)
    speech_start = int(1.2 * TARGET_SR)
    audio[speech_start : speech_start + TARGET_SR // 2] = 10000

    window = _loudest_window(audio, int(1.5 * TARGET_SR))

    assert np.abs(window).sum() > 0
    assert np.abs(window).max() == 10000


def test_loudest_window_returns_the_requested_length() -> None:
    audio = np.full(3 * TARGET_SR, 5000, dtype=np.int16)
    target = int(1.5 * TARGET_SR)

    assert len(_loudest_window(audio, target)) == target


def test_sliding_windows_include_partial_ones_at_the_edges() -> None:
    """A positive is "silence, short word, silence" — and so is the onset of
    any sentence. Negatives have to contain onsets, or every onset scores
    high."""
    audio = np.full(3 * TARGET_SR, 8000, dtype=np.int16)
    target = int(1.5 * TARGET_SR)
    rng = np.random.default_rng(0)

    windows = _sliding_windows(audio, target, n=40, rng=rng)

    assert all(len(w) == target for w in windows)
    # At least one window straddles an edge, i.e. is part silence.
    assert any((w == 0).any() for w in windows)
    # And at least one is fully inside the recording.
    assert any((w != 0).all() for w in windows)


def test_silence_and_noise_clips_are_always_available() -> None:
    """A wake-word model has to reject silence; a live listener spends nearly
    all its time looking at exactly that. Training without these produced a
    model scoring 1.0 on pure silence."""
    rng = np.random.default_rng(0)

    clips = _silence_and_noise_clips(rng, n=30)

    assert len(clips) == 30
    assert all(len(c) == int(1.5 * TARGET_SR) for c in clips)
    assert any((c == 0).all() for c in clips)  # some pure silence
    assert any((c != 0).any() for c in clips)  # some faint noise


def test_generated_noise_stays_quiet() -> None:
    """These stand in for a quiet room, not for speech — loud noise labelled
    negative would teach the wrong boundary."""
    rng = np.random.default_rng(0)

    peaks = [np.abs(c).max() / 32768 for c in _silence_and_noise_clips(rng, n=40)]

    assert max(peaks) < 0.2
