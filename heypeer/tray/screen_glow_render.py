"""The screen-edge glow - light around all four sides while Hey Peer is up.

## What this is

The effect the user asked for, after iOS: when Siri is listening, the
screen's own perimeter glows in Siri's colours, brightest in dark mode. It
says "the assistant is active" without occupying anything - no panel, no
window to dismiss, nothing over what you were reading.

It is the same idea as the blob's aura and deliberately the same palette,
but a different object: the blob is *where* Hey Peer is, the border is
*that* Hey Peer is. Both on screen at once reads as one system rather than
two, which is why the hue and its rotation come from the same constants.

## Why a frame rather than a full-screen image

A full-screen RGBA bitmap at 1920x1080 is 8MB per frame, and this animates.
Only the outer band is ever non-transparent, so only the band is drawn: four
strips composited into an otherwise empty image, at a fraction of the cost.
The middle is never touched, which also guarantees it stays perfectly
transparent - there is nothing there to accidentally tint.

## Why it is cheap enough to animate

The gradient across the band's width does not change from frame to frame -
only its hue does. So the falloff is computed once as a 1-D profile and
broadcast, and each frame is a hue lookup plus a multiply. What would be
per-pixel work at 1920x1080 is per-*column* work at the band's depth.
"""

import math

import numpy as np
from PIL import Image

from heypeer.tray.blob_render import _ramp

# How deep the glow reaches in from each edge, as a fraction of the screen's
# shorter side. Wide enough to read as light spilling in, narrow enough that
# it never competes with what the user is actually looking at.
DEPTH_FRACTION = 0.055
MIN_DEPTH_PX = 28
MAX_DEPTH_PX = 110

# Peak opacity at the very edge. Deliberately modest: this sits over the
# user's work for the whole time Hey Peer is up, and anything stronger stops
# being ambient and starts being in the way.
EDGE_ALPHA = 0.72

# How fast the hue travels around the border, in turns per unit phase. Slow
# on purpose - the blob's aura is the busy element, and a border cycling at
# the same rate would fight it for attention.
HUE_SPEED = 0.18


def depth_for(width: int, height: int) -> int:
    """How many pixels deep the band is on a screen of this size."""
    shorter = min(width, height)
    return int(max(MIN_DEPTH_PX, min(MAX_DEPTH_PX, shorter * DEPTH_FRACTION)))


def _falloff(depth: int) -> np.ndarray:
    """Opacity from the outer edge inward, 1 at the edge and 0 at the
    inner boundary.

    Cubed rather than linear: a linear ramp has a visible straight line
    where it reaches zero, because the eye finds the discontinuity in the
    *slope*. Cubing lands it softly enough that the band has no inner edge
    at all.
    """
    t = np.linspace(0.0, 1.0, max(1, depth), dtype=np.float32)
    fade = 1.0 - t
    return fade * fade * fade


def render(width: int, height: int, phase: float = 0.0, intensity: float = 1.0) -> Image.Image:
    """One frame of the border glow, sized to the whole screen.

    `phase` rotates the hue around the border; `intensity` scales the whole
    thing, so a caller can fade it in and out rather than having it appear
    and vanish.
    """
    intensity = min(1.0, max(0.0, intensity))
    image = np.zeros((height, width, 4), dtype=np.float32)
    if intensity <= 0:
        return Image.fromarray(image.astype(np.uint8), mode="RGBA")

    depth = depth_for(width, height)
    fade = _falloff(depth) * EDGE_ALPHA * intensity

    # Four hues, one per side, spaced a quarter-turn apart so the colour
    # travels around the frame rather than pulsing all four sides in
    # unison - the difference between light circling the screen and the
    # whole border blinking.
    ramp = _ramp()
    def hue(offset: float):
        return ramp[int(((phase * HUE_SPEED + offset) % 1.0) * 255)]

    top, right, bottom, left = (hue(o) for o in (0.0, 0.25, 0.5, 0.75))

    # Vertical bands, then horizontal. Written with maximum() rather than
    # addition so the corners - where two bands overlap - stay at the same
    # opacity as the edges instead of doubling into bright blots.
    for band_colour, rows in ((top, slice(0, depth)), (bottom, slice(height - depth, height))):
        profile = fade if rows.start == 0 else fade[::-1]
        strip = image[rows]
        alpha = profile[:, None]
        strip[..., :3] = np.maximum(strip[..., :3], band_colour * np.ones((depth, width, 1), np.float32))
        strip[..., 3] = np.maximum(strip[..., 3], np.broadcast_to(alpha, (depth, width)))

    for band_colour, cols in ((left, slice(0, depth)), (right, slice(width - depth, width))):
        profile = fade if cols.start == 0 else fade[::-1]
        strip = image[:, cols]
        alpha = profile[None, :]
        strip[..., :3] = np.maximum(strip[..., :3], band_colour * np.ones((height, depth, 1), np.float32))
        strip[..., 3] = np.maximum(strip[..., 3], np.broadcast_to(alpha, (height, depth)))

    image[..., 3] *= 255.0
    return Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), mode="RGBA")
