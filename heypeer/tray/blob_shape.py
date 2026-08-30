"""The blob's silhouette, as a radius that varies with angle and time.

    R(theta) = R0 * (1 + A * N(theta, phase))

`N` is band-limited procedural noise: a sum of a few sinusoidal harmonics
whose phases drift at unrelated speeds. That is deliberate rather than a
shortcut around Perlin/Simplex — being band-limited *guarantees* the outline
can never develop a spike or a corner, however the amplitude is driven,
which is the one property the design cannot do without. Incommensurate drift
speeds mean it never visibly repeats.

`A` is the energy, not the size. Silence still deforms the shape (`A` never
reaches zero), and a loud voice makes it churn rather than merely inflate.

Phase is *accumulated* by the caller rather than computed from wall-clock
time. If harmonics were evaluated as `sin(k*theta + speed*t)`, every change
in speed would instantly rewrite the phase and the shape would jump — which
is precisely the kind of discontinuity the smoothing elsewhere exists to
avoid.
"""

import math

import numpy as np

# (harmonic, relative weight, drift speed). Low harmonics make broad lobes,
# high ones the fine ripple along the rim. Weights fall off with frequency so
# the outline stays rounded; speeds are mutually irrational so the loop never
# closes.
_HARMONICS = (
    (2, 0.30, 0.11),
    (3, 0.55, 0.42),
    (4, 0.38, -0.31),
    (5, 0.26, 0.23),
    (7, 0.14, 0.17),
    (9, 0.08, -0.13),
)

# Largest amplitude the renderer sizes its frame for; beyond this the glow
# would be clipped by the edge of the bitmap.
MAX_AMPLITUDE = 0.30


def radius_profile(n_angles: int, phase: float, amplitude: float) -> np.ndarray:
    """Radius per angle, normalised around 1.0.

    `amplitude` is how far the outline may stray from a circle — 0.03 reads
    as a sphere breathing, 0.25 as a churning blob.
    """
    angles = np.linspace(-math.pi, math.pi, n_angles, endpoint=False)
    noise = sum(
        weight * np.sin(harmonic * angles + speed * phase)
        for harmonic, weight, speed in _HARMONICS
    )
    # Normalised by its own peak, not by the sum of the weights. Sinusoids
    # at unrelated phases almost never align, so the sum only ever reached
    # about three quarters of that sum - `amplitude` promised a deformation
    # and quietly delivered 78% of it, which is part of why the motion read
    # as barely there. Dividing by the actual peak makes the number mean
    # exactly what it says.
    peak = float(np.abs(noise).max())
    if peak > 0:
        noise = noise / peak
    return 1.0 + amplitude * noise
