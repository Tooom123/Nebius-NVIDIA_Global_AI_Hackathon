"""Tests for the blob's outline.

The properties that matter are the ones the design depends on: the silhouette
is always smooth (never spiky, whatever drives it), it never stops moving,
and amplitude changes its *character* rather than merely its size.
"""

import numpy as np

from heypeer.tray.blob_shape import MAX_AMPLITUDE, radius_profile

N = 512


def test_profile_is_centred_on_one() -> None:
    """Radii are normalised, so the renderer alone decides pixel size."""
    profile = radius_profile(N, phase=1.0, amplitude=0.1)

    assert 0.98 < float(np.mean(profile)) < 1.02


def test_outline_stays_within_the_amplitude_it_was_given() -> None:
    """The renderer sizes the frame from the amplitude, so exceeding it would
    push the glow off the edge of the bitmap."""
    for amplitude in (0.03, 0.15, MAX_AMPLITUDE):
        profile = radius_profile(N, phase=2.0, amplitude=amplitude)
        assert profile.max() <= 1 + amplitude + 1e-9
        assert profile.min() >= 1 - amplitude - 1e-9


def test_outline_is_smooth_never_spiky() -> None:
    """Band-limited by construction - a sum of low harmonics cannot produce a
    corner however hard the amplitude is driven. This is the one property the
    design cannot do without."""
    profile = radius_profile(N, phase=1.0, amplitude=MAX_AMPLITUDE)
    step = np.abs(np.diff(np.concatenate([profile, profile[:1]])))

    # No single angular step moves the radius by more than a fraction of a
    # percent of the mean.
    assert step.max() < 0.02


def test_amplitude_controls_how_far_it_strays_from_a_circle() -> None:
    def spread(amplitude: float) -> float:
        profile = radius_profile(N, phase=1.0, amplitude=amplitude)
        return float(profile.max() - profile.min())

    assert spread(0.25) > spread(0.10) > spread(0.03)


def test_a_tiny_amplitude_is_almost_a_sphere() -> None:
    """The design's idle state: breathing at about 3%, and the state a
    transition returns to."""
    profile = radius_profile(N, phase=1.0, amplitude=0.03)

    assert float(profile.max() - profile.min()) < 0.06


def test_it_never_stops_moving() -> None:
    """Even in silence a procedural noise keeps deforming the radius."""
    assert not np.array_equal(
        radius_profile(N, phase=0.0, amplitude=0.03),
        radius_profile(N, phase=2.5, amplitude=0.03),
    )


def test_the_outline_is_continuous_around_the_circle() -> None:
    """First and last angle are neighbours; a seam there would show as a
    crease running out from the centre."""
    profile = radius_profile(N, phase=3.0, amplitude=0.2)

    assert abs(float(profile[0] - profile[-1])) < 0.02


def test_motion_is_smooth_in_time_as_well_as_angle() -> None:
    """A small step in phase must give a small change in shape, or the
    animation stutters however fast it is rendered."""
    a = radius_profile(N, phase=1.000, amplitude=0.2)
    b = radius_profile(N, phase=1.033, amplitude=0.2)  # one frame at 30fps

    assert float(np.abs(b - a).max()) < 0.02


def test_profile_length_matches_the_requested_angles() -> None:
    assert len(radius_profile(128, phase=0.0, amplitude=0.1)) == 128
