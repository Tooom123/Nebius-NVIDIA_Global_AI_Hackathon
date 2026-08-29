"""Tests for the blob outline.

This geometry drives both the window region and what the user sees, so the
properties that matter are: it never escapes the window (anything outside is
clipped away and would look truncated — the exact complaint that motivated
this module), it's genuinely irregular rather than a circle, it moves over
time, and it grows with the mic level.
"""

import math

from heypeer.tray.blob_shape import blob_points

W = H = 210


def _radii(points: "list[tuple[int, int]]") -> "list[float]":
    return [math.hypot(x - W / 2, y - H / 2) for x, y in points]


def test_outline_always_fits_inside_the_window() -> None:
    """Anything outside the window is clipped, which is what made the
    previous fixed-ellipse version look cut off."""
    for t in [0.0, 1.3, 7.7, 42.0]:
        for level in [0.0, 0.5, 1.0]:
            for x, y in blob_points(W, H, t=t, level=level):
                assert 0 <= x <= W
                assert 0 <= y <= H


def test_outline_is_irregular_not_a_circle() -> None:
    radii = _radii(blob_points(W, H, t=2.0))

    assert max(radii) - min(radii) > 5  # visibly blobby, not a disc


def test_outline_is_closed_and_smooth() -> None:
    """Neighbouring points stay close together, so neither the window region
    nor the eye sees facets."""
    points = blob_points(W, H, t=1.0)
    steps = [
        math.dist(points[i], points[(i + 1) % len(points)]) for i in range(len(points))
    ]

    assert max(steps) < 12


def test_outline_changes_over_time() -> None:
    assert blob_points(W, H, t=0.0) != blob_points(W, H, t=2.5)


def test_outline_grows_with_the_mic_level() -> None:
    quiet = sum(_radii(blob_points(W, H, t=1.0, level=0.0)))
    loud = sum(_radii(blob_points(W, H, t=1.0, level=1.0)))

    assert loud > quiet * 1.1


def test_level_is_clamped() -> None:
    assert blob_points(W, H, t=1.0, level=5.0) == blob_points(W, H, t=1.0, level=1.0)
    assert blob_points(W, H, t=1.0, level=-3.0) == blob_points(W, H, t=1.0, level=0.0)


def test_point_count_is_configurable() -> None:
    assert len(blob_points(W, H, t=0.0, n_points=40)) == 40
