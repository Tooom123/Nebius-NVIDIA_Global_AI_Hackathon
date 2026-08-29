"""Geometry for the animated blob indicator.

Kept as a pure function of (time, level) deliberately, with no drawing and
no Win32 in it, because the exact same outline has to drive two different
things that must never disagree:

* the **window region** (`SetWindowRgn`), which is what actually removes the
  rectangular window edge, and
* the page's **`clip-path`**, which is what the gradient is clipped to.

Earlier attempts animated the silhouette in CSS and clipped the window to a
fixed shape. Those can't stay in sync: whatever the window region doesn't
cover is chopped off, and whatever the page doesn't paint shows through as
the window's grey background. Deriving both from one function here removes
that whole class of bug — and it makes the shape unit-testable without a
display, which nothing about the previous CSS-animated version was.

The outline is a radius modulated by a few low-frequency harmonics:

    r(θ, t) = R · (1 + Σ aᵢ·sin(kᵢ·θ + ωᵢ·t + φᵢ))

Three harmonics with small amplitudes give the slow, organic wobble of the
reference design; more or larger ones read as spiky rather than blobby.
"""

import math

# (harmonic, amplitude, angular speed rad/s, phase). Deliberately
# non-integer speed ratios so the shape never visibly repeats.
_HARMONICS = (
    (3, 0.055, 0.42, 0.0),
    (4, 0.038, -0.31, 1.7),
    (5, 0.026, 0.23, 3.1),
)

# How much the blob swells at full mic level.
LEVEL_SCALE = 0.16
# Radius headroom so the biggest possible outline still fits the window with
# room for the glow: base radius is the inscribed radius divided by this.
_MAX_EXTENT = 1 + sum(a for _k, a, _w, _p in _HARMONICS) + LEVEL_SCALE + 0.06


def blob_points(
    width: int, height: int, t: float, level: float = 0.0, n_points: int = 72
) -> list[tuple[int, int]]:
    """Outline of the blob at time `t` (seconds) and mic `level` (0-1), as
    integer pixel coordinates inside a `width` x `height` window.

    `n_points` at 72 is one point per 5 degrees — smooth enough that neither
    the window region nor the clip-path shows facets at this size, and far
    too few points to matter for either's cost.
    """
    level = max(0.0, min(1.0, level))
    cx, cy = width / 2, height / 2
    base_radius = min(width, height) / 2 / _MAX_EXTENT
    radius = base_radius * (1 + LEVEL_SCALE * level)

    points = []
    for i in range(n_points):
        theta = 2 * math.pi * i / n_points
        wobble = sum(
            amplitude * math.sin(harmonic * theta + speed * t + phase)
            for harmonic, amplitude, speed, phase in _HARMONICS
        )
        r = radius * (1 + wobble)
        points.append((round(cx + r * math.cos(theta)), round(cy + r * math.sin(theta))))
    return points
