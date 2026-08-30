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

SIZE = 240
BASE = SIZE * 0.26


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


def _solid_area(amplitude: float, radius: float) -> int:
    frame = render(SIZE, radius_profile(OUTLINE_ANGLES, 1.0, amplitude), radius)
    return int((_alpha(frame) > 245).sum())


def test_the_voice_visibly_changes_the_shape() -> None:
    """Regression test: the level was reaching the renderer but the gains
    were so timid (the radius term moved it 1.5% at speaking volume) that
    nothing appeared to happen when the user spoke."""
    from heypeer.tray.debug_window import (
        BASE_RADIUS,
        LEVEL_AMPLITUDE_GAIN,
        LEVEL_RADIUS_GAIN,
        STATE_ENERGY,
    )

    recording = STATE_ENERGY["recording"]
    silent = _solid_area(recording["amplitude"], BASE_RADIUS)
    loud = _solid_area(
        recording["amplitude"] + LEVEL_AMPLITUDE_GAIN,
        BASE_RADIUS * (1 + LEVEL_RADIUS_GAIN),
    )

    assert loud > silent * 1.15  # plainly visible, not a 1% nudge


def test_no_state_or_level_clips_against_the_frame() -> None:
    """The frame has to hold the largest shape any state can reach, glow
    included - a halo cut off by the bitmap edge shows as a straight line."""
    from heypeer.tray.debug_window import (
        BASE_RADIUS,
        LEVEL_AMPLITUDE_GAIN,
        LEVEL_RADIUS_GAIN,
        STATE_ENERGY,
    )

    for energy in STATE_ENERGY.values():
        gain = energy["level_gain"]
        frame = render(
            SIZE,
            radius_profile(OUTLINE_ANGLES, 1.0, energy["amplitude"] + LEVEL_AMPLITUDE_GAIN * gain),
            BASE_RADIUS * (1 + LEVEL_RADIUS_GAIN * gain),
            glow=1.0,
        )
        alpha = _alpha(frame)
        assert max(
            alpha[0, :].max(), alpha[-1, :].max(), alpha[:, 0].max(), alpha[:, -1].max()
        ) == 0


def _luminance(image) -> np.ndarray:
    return np.asarray(image)[..., :3].mean(axis=-1)


def _sample(lum: np.ndarray, fx: float, fy: float, radius: float) -> float:
    """Luminance at a point given as a fraction of the blob's radius from its
    centre, so a probe means the same thing whatever the blob's size."""
    centre = (SIZE - 1) / 2
    return float(lum[int(centre + fy * radius), int(centre + fx * radius)])


def test_the_lit_side_is_much_brighter_than_the_shadowed_side() -> None:
    """Diffuse shading is what makes the form read as a volume rather than a
    disc with a gradient on it. The light comes from the upper left, so that
    quadrant of the surface has to be plainly brighter than the lower right."""
    lum = _luminance(_frame(amplitude=0.03))

    lit = _sample(lum, -0.5, -0.5, BASE)
    shadowed = _sample(lum, 0.5, 0.5, BASE)

    assert lit > shadowed * 2


def test_there_is_a_tight_specular_highlight() -> None:
    """A small hard bright spot, not a broad sheen: it is the single strongest
    signal that a surface is curved and glossy. Tight means it covers a small
    fraction of the body, bright means it stands well clear of the rest."""
    frame = _frame(amplitude=0.03)
    lum = _luminance(frame)
    body = _alpha(frame) > 245

    assert lum[body].max() > np.median(lum[body]) * 2
    # Confined: only a small part of the surface is near that peak.
    near_peak = (lum > lum[body].max() * 0.92) & body
    assert 0 < near_peak.sum() < body.sum() * 0.06


def test_the_silhouette_lights_up_against_a_darker_shoulder() -> None:
    """The Fresnel edge. Without the dark band just inside it the rim light
    merges into the body and the sphericity collapses back into a flat disc,
    so the ordering of these three samples is the property that matters."""
    lum = _luminance(_frame(amplitude=0.03))

    mid = _sample(lum, 0.35, 0.35, BASE)
    shoulder = _sample(lum, 0.62, 0.62, BASE)
    rim = _sample(lum, 0.70, 0.70, BASE)

    assert shoulder < mid
    assert rim > shoulder


def test_the_shading_is_anchored_to_the_blob_not_to_the_frame() -> None:
    """Regression test for what made the old look flat.

    The colour used to be a radial gradient measured in *frame* coordinates,
    with its highlight pinned at a fixed fraction of the bitmap. Growing or
    shrinking the blob therefore slid the shading across it - the light did
    not belong to the object, which is exactly why the user saw "bien anime
    mais seulement en 2D". Shading from the surface normal makes the
    highlight sit at the same place *on the sphere* whatever its size.
    """

    def highlight_offset(radius: float) -> tuple[float, float]:
        frame = render(SIZE, radius_profile(OUTLINE_ANGLES, 0.0, 0.03), radius)
        lum = np.where(_alpha(frame) > 245, _luminance(frame), -1.0)
        iy, ix = np.unravel_index(np.argmax(lum), lum.shape)
        centre = (SIZE - 1) / 2
        return (ix - centre) / radius, (iy - centre) / radius

    small = highlight_offset(SIZE * 0.20)
    large = highlight_offset(SIZE * 0.32)

    assert small[0] == pytest.approx(large[0], abs=0.05)
    assert small[1] == pytest.approx(large[1], abs=0.05)


def test_the_palette_reaches_violet_on_the_shadowed_side() -> None:
    """Cyan lit, violet grazing. An earlier version only ever reached violet
    in a thin crescent at the very bottom, so the blob read as uniformly blue
    - the complaint the palette existed to answer."""
    frame = _frame(amplitude=0.03)
    rgb = np.asarray(frame)[..., :3].astype(int)
    body = _alpha(frame) > 245

    # Red above green is exactly what separates violet from the rest of the
    # ramp: #7C3AED has more red than green, #2563EB and #7DD3FC both have
    # more green than red. Checking the hue rather than an absolute colour
    # keeps this honest about a shadowed side that is legitimately dark.
    violet = body & (rgb[..., 0] > rgb[..., 1] + 4) & (rgb[..., 2] > rgb[..., 0])

    assert violet.sum() > body.sum() * 0.05
