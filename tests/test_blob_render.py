"""Tests for the indicator's rendering.

These are the checks that were impossible while the look lived in CSS behind
a web view: the actual pixels are inspectable here, so the properties that
kept regressing on real hardware — a visible background, hard edges, no glow
— are now assertions rather than something only the user could catch.
"""

import numpy as np
import pytest

from heypeer.tray.blob_render import compose, render_alpha, render_blob

PALETTE = ((79, 140, 255), (123, 77, 255), (224, 64, 251))
SIZE = 160


def _alpha_of(image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"))[..., 3]


def test_frame_is_rgba_of_the_requested_size() -> None:
    frame = render_blob(SIZE, t=0.0, level=0.0, colors=PALETTE)

    assert frame.mode == "RGBA"
    assert frame.size == (SIZE, SIZE)


def test_corners_are_fully_transparent() -> None:
    """There is no background — this is what every SetWindowRgn/transparency
    attempt failed to achieve, showing a grey or black rectangle instead."""
    alpha = _alpha_of(render_blob(SIZE, t=0.0, level=0.0, colors=PALETTE))

    assert alpha[0, 0] == 0
    assert alpha[0, -1] == 0
    assert alpha[-1, 0] == 0
    assert alpha[-1, -1] == 0


def test_centre_is_fully_opaque() -> None:
    alpha = _alpha_of(render_blob(SIZE, t=0.0, level=0.0, colors=PALETTE))

    assert alpha[SIZE // 2, SIZE // 2] == 255


def test_edges_are_antialiased_not_hard() -> None:
    """A window region gives a 1-bit mask: every pixel either fully on or
    fully off, which is what made the previous version look jagged. Real
    per-pixel alpha means a substantial band of partial values."""
    alpha = _alpha_of(render_blob(SIZE, t=0.0, level=0.0, colors=PALETTE))

    partial = ((alpha > 10) & (alpha < 245)).sum()

    assert partial > alpha.size * 0.05


def test_glow_extends_beyond_the_solid_silhouette() -> None:
    """The glow is what a 1-bit region could not express at all."""
    alpha = _alpha_of(render_blob(SIZE, t=0.0, level=0.0, colors=PALETTE))

    solid = (alpha > 245).sum()
    lit = (alpha > 20).sum()

    assert lit > solid * 1.15


def test_blob_grows_with_the_mic_level() -> None:
    quiet = (_alpha_of(render_blob(SIZE, t=1.0, level=0.0, colors=PALETTE)) > 245).sum()
    loud = (_alpha_of(render_blob(SIZE, t=1.0, level=1.0, colors=PALETTE)) > 245).sum()

    assert loud > quiet


def test_shape_changes_over_time() -> None:
    first = _alpha_of(render_blob(SIZE, t=0.0, level=0.0, colors=PALETTE))
    later = _alpha_of(render_blob(SIZE, t=3.0, level=0.0, colors=PALETTE))

    assert not np.array_equal(first, later)


def test_gradient_actually_varies_across_the_blob() -> None:
    """A flat fill would read as a disc rather than a lit volume."""
    frame = render_blob(SIZE, t=0.0, level=0.0, colors=PALETTE)
    rgb = np.asarray(frame)[..., :3]
    opaque = np.asarray(frame)[..., 3] > 245

    assert rgb[opaque].std(axis=0).max() > 15


def test_alpha_is_independent_of_palette() -> None:
    """`render_alpha` is cached across states precisely because colour never
    affects it — if that stopped holding, states would render stale shapes."""
    alpha = render_alpha(SIZE, t=2.0, level=0.3)
    warm = compose(alpha, PALETTE)
    cool = compose(alpha, ((10, 200, 120), (20, 120, 200), (90, 90, 240)))

    assert np.array_equal(_alpha_of(warm), _alpha_of(cool))
    assert not np.array_equal(np.asarray(warm)[..., :3], np.asarray(cool)[..., :3])


@pytest.mark.parametrize("level", [0.0, 0.5, 1.0])
def test_nothing_is_clipped_at_the_frame_border(level: float) -> None:
    """The glow has to fade out inside the image; if it were cut off at the
    border the overlay would show a straight edge."""
    alpha = _alpha_of(render_blob(SIZE, t=1.5, level=level, colors=PALETTE))

    assert alpha[0, :].max() == 0
    assert alpha[-1, :].max() == 0
    assert alpha[:, 0].max() == 0
    assert alpha[:, -1].max() == 0
