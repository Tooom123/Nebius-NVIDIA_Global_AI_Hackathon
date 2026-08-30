"""Tests for the indicator's rendering.

These are the checks that were impossible while the look lived in CSS behind
a web view: the actual pixels are inspectable here, so the properties that
kept regressing on real hardware — a visible background, hard edges, no glow
— are assertions rather than something only the user could catch.
"""

import numpy as np
import pytest

from heypeer.tray.blob_render import OUTLINE_ANGLES, render
from heypeer.tray.blob_shape import radius_profile

SIZE = 160
BASE = SIZE * 0.30


def _frame(phase: float = 0.0, amplitude: float = 0.08, glow: float = 1.0):
    return render(SIZE, radius_profile(OUTLINE_ANGLES, phase, amplitude), BASE, glow)


def _alpha(image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"))[..., 3]


def test_frame_is_rgba_of_the_requested_size() -> None:
    frame = _frame()

    assert frame.mode == "RGBA"
    assert frame.size == (SIZE, SIZE)


def test_corners_are_fully_transparent() -> None:
    """There is no background — this is what every window-region and
    transparency attempt failed to achieve, showing a grey or black rectangle
    instead."""
    alpha = _alpha(_frame())

    assert alpha[0, 0] == 0
    assert alpha[0, -1] == 0
    assert alpha[-1, 0] == 0
    assert alpha[-1, -1] == 0


def test_centre_is_fully_opaque() -> None:
    assert _alpha(_frame())[SIZE // 2, SIZE // 2] == 255


def test_edges_are_antialiased_not_hard() -> None:
    """A window region gives a 1-bit mask: every pixel fully on or fully off,
    which is what made an earlier version look jagged."""
    alpha = _alpha(_frame())

    partial = ((alpha > 10) & (alpha < 245)).sum()

    assert partial > alpha.size * 0.05


def test_glow_extends_beyond_the_solid_shape() -> None:
    alpha = _alpha(_frame())

    solid = (alpha > 245).sum()
    lit = (alpha > 20).sum()

    assert lit > solid * 1.15


def test_glow_strength_is_controllable_without_changing_the_shape() -> None:
    """Energy shows through the halo, so a state can feel more alive without
    the silhouette changing size."""
    faint = _alpha(_frame(glow=0.2))
    strong = _alpha(_frame(glow=1.0))

    assert (strong > 20).sum() > (faint > 20).sum()
    # The solid body is the same either way.
    assert (strong > 245).sum() == pytest.approx((faint > 245).sum(), rel=0.02)


def test_nothing_is_clipped_at_the_frame_border() -> None:
    """The glow has to fade out inside the image; clipped, the overlay would
    show a straight edge."""
    for amplitude in (0.03, 0.15, 0.30):
        alpha = _alpha(_frame(amplitude=amplitude))
        assert alpha[0, :].max() == 0
        assert alpha[-1, :].max() == 0
        assert alpha[:, 0].max() == 0
        assert alpha[:, -1].max() == 0


def test_shape_changes_as_the_phase_advances() -> None:
    assert not np.array_equal(_alpha(_frame(phase=0.0)), _alpha(_frame(phase=3.0)))


def test_higher_amplitude_gives_a_less_circular_outline() -> None:
    """Amplitude is energy, not size: it makes the form churn."""

    def roundness(amplitude: float) -> float:
        profile = radius_profile(OUTLINE_ANGLES, 1.0, amplitude)
        return float(profile.max() - profile.min())

    assert roundness(0.25) > roundness(0.03)


def test_the_gradient_actually_varies_across_the_blob() -> None:
    """A flat fill would read as a disc rather than a lit volume."""
    frame = _frame()
    rgb = np.asarray(frame)[..., :3]
    opaque = np.asarray(frame)[..., 3] > 245

    assert rgb[opaque].std(axis=0).max() > 15


def test_palette_is_the_cyan_blue_violet_of_the_design() -> None:
    from heypeer.tray.blob_render import PALETTE_BLUE, PALETTE_CYAN, PALETTE_VIOLET

    assert PALETTE_CYAN == (125, 211, 252)  # #7DD3FC
    assert PALETTE_BLUE == (37, 99, 235)  # #2563EB
    assert PALETTE_VIOLET == (124, 58, 237)  # #7C3AED
