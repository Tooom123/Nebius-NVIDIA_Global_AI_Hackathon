"""Renders the blob to an RGBA image with real per-pixel alpha.

Drawn as an analytic radial field rather than a filled polygon: for every
pixel, its angle gives the outline's radius there, and its distance from the
centre decides whether it is inside the blob, on its soft edge, or in the
surrounding glow.

That replaces a polygon fill at 3x supersample followed by a gaussian blur.
The old approach cost ~18ms a frame, which forced pre-rendering a short loop
of frames and cycling them — the shape then advanced only a few times a
second and the result looked stepped. This costs ~1.4ms, so every frame can
be rendered live at 30fps from continuously varying parameters, which is
what actually makes the motion smooth. Antialiasing and the glow fall out of
the field itself instead of being approximated by supersampling and blur.

Output is fully transparent wherever the blob and its glow aren't; there is
no background of any kind (see `overlay.py` for why that matters).
"""

import math
from functools import lru_cache

import numpy as np
from PIL import Image

# Cyan sits off-centre toward the top so the form reads as lit from above and
# volumetric rather than flat.
PALETTE_CYAN = (125, 211, 252)
PALETTE_BLUE = (37, 99, 235)
PALETTE_VIOLET = (124, 58, 237)
HIGHLIGHT_CENTER = (0.42, 0.32)

# Width in pixels over which the edge fades from opaque to transparent. About
# a pixel and a half reads as crisp but never jagged.
EDGE_SOFTNESS_PX = 1.6

# Glow reach as a fraction of the blob's radius, and its peak opacity.
GLOW_REACH = 0.26
GLOW_ALPHA = 0.55

# Angular resolution of the outline. Finer than the eye can resolve at this
# size, and the cost is a single interpolation regardless.
OUTLINE_ANGLES = 512


@lru_cache(maxsize=4)
def _geometry(size: int):
    """Per-pixel distance and angle from the centre. Constant for a given
    frame size, so computed once."""
    ys, xs = np.mgrid[0:size, 0:size]
    centre = (size - 1) / 2
    dx = xs - centre
    dy = ys - centre
    return np.sqrt(dx * dx + dy * dy), np.arctan2(dy, dx)


@lru_cache(maxsize=4)
def _angles(n: int) -> np.ndarray:
    return np.linspace(-math.pi, math.pi, n, endpoint=False)


@lru_cache(maxsize=16)
def _colours(size: int, radius_px: int) -> np.ndarray:
    """Radial gradient through cyan, blue and violet, plus a soft specular
    lift. Cached on size and radius: it never depends on the animation, and
    recomputing it every frame would dominate the per-frame cost."""
    ys, xs = np.mgrid[0:size, 0:size]
    hx, hy = HIGHLIGHT_CENTER
    dx = xs / (size - 1) - hx
    dy = ys / (size - 1) - hy

    # Normalised over the *blob*, not the frame. Spanning the whole bitmap
    # meant the gradient only ever travelled from 0.27 to 0.58 inside the
    # shape - so violet, which sits at 1.0, was never reached at all and the
    # blob came out uniformly blue. The span is the distance from the
    # off-centre highlight to the far side of the blob.
    span = math.hypot(0.5 - hx, 0.5 - hy) + radius_px / size
    distance = np.clip(np.sqrt(dx * dx + dy * dy) / span, 0, 1)

    stops = np.array([0.0, 0.55, 1.0])
    ramp = [PALETTE_CYAN, PALETTE_BLUE, PALETTE_VIOLET]
    rgb = np.stack(
        [np.interp(distance, stops, [c[i] for c in ramp]) for i in range(3)], axis=-1
    )

    # A tight bright core where the "light" sits, for the wet, glassy look of
    # the reference rather than a flat gradient.
    specular = np.clip(1 - distance / 0.42, 0, 1) ** 3 * 0.55
    rgb = rgb + (255 - rgb) * specular[..., None]
    return np.clip(rgb, 0, 255)


def render(
    size: int,
    radii: np.ndarray,
    base_radius: float,
    glow: float = 1.0,
) -> Image.Image:
    """One RGBA frame.

    `radii` is a per-angle outline (see `blob_shape.radius_profile`), scaled
    by `base_radius` in pixels. `glow` scales the halo, which is how the
    energy of a state shows without changing the silhouette's size.
    """
    distance, theta = _geometry(size)
    outline = (
        np.interp(theta, _angles(len(radii)), radii, period=2 * math.pi) * base_radius
    )

    # Signed distance to the outline: negative inside, positive outside.
    outside = distance - outline

    body = np.clip(0.5 - outside / EDGE_SOFTNESS_PX, 0, 1)
    # Compact support, not an exponential: the halo must reach exactly zero
    # within GLOW_REACH. An exponential only ever approaches zero, so it was
    # still faintly non-zero at the frame border, and a glow cut off by the
    # edge of the bitmap shows as a straight line across it.
    halo = np.clip(1 - np.clip(outside, 0, None) / (base_radius * GLOW_REACH), 0, 1) ** 2
    alpha = np.maximum(body, halo * GLOW_ALPHA * glow) * 255

    # Rounded so a radius drifting by a pixel doesn't thrash the cache.
    rgba = np.dstack(
        [_colours(size, int(round(base_radius / 2)) * 2), np.clip(alpha, 0, 255)]
    )
    return Image.fromarray(rgba.astype(np.uint8), mode="RGBA")
