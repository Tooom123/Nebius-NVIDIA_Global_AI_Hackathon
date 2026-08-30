"""Renders the indicator's blob to an RGBA image, with real per-pixel alpha.

Why this exists at all: five rounds of trying to get a borderless, good
looking indicator out of a web view failed on the same wall each time. A
`pywebview`/WebView2 window can be made rectangular-but-transparent (which
kept showing the WinForms form's grey behind it) or clipped with
`SetWindowRgn` (which works, but a window region is a 1-bit mask — hard,
aliased edges and no way to render a glow). Neither can produce the soft,
luminous edge the reference design is built around.

Drawing the frame ourselves and handing it to `UpdateLayeredWindow` (see
`overlay.py`) does give per-pixel alpha: antialiased edges, a real glow that
fades to nothing, no background of any kind. It is the standard way polished
Windows overlays are built, and it removes the browser engine — and its
whole class of failure modes — from the indicator entirely.

Keeping the rendering here, as pure PIL/numpy with no Win32 and no window,
also means the visual result is *testable*: alpha at the corners, softness
of the edge, the glow extending past the silhouette, and growth with the mic
level are all assertable headlessly. None of that was checkable when the
look lived in CSS.
"""

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from heypeer.tray.blob_shape import blob_points

# Renders at this multiple then downsamples, which is what actually produces
# the antialiased edge (the polygon itself is drawn with a hard 1-bit fill).
SUPERSAMPLE = 3

# Glow thickness as a fraction of the image size, and how far its alpha
# reaches. Deliberately wide and faint: the reference look is a light source,
# not an outline.
GLOW_BLUR_RATIO = 0.055
GLOW_ALPHA = 0.55

# Fraction of the canvas the blob itself occupies, leaving room for the glow
# to fade out inside the image rather than being clipped at its edge.
BLOB_INSET = 0.76

# Lighting for the spherical shading (see `_gradient`). The light sits up
# and to the left, matching the reference design's highlight.
LIGHT_DIRECTION = (-0.45, -0.55, 0.70)
# Floor brightness on the unlit side — without it the far edge goes black
# instead of staying a deep saturated colour.
AMBIENT = 0.62
# Tight bright spot facing the light. Higher sharpness = smaller, glossier.
SPECULAR_STRENGTH = 0.5
SPECULAR_SHARPNESS = 6.0
# Light picked up along the silhouette, so the edge reads as curved.
RIM_STRENGTH = 0.16
RIM_SHARPNESS = 2.5


@lru_cache(maxsize=16)
def _gradient(size: int, colors: "tuple[tuple[int, int, int], ...]") -> np.ndarray:
    """A shaded sphere in `colors`, as an (size, size, 3) uint8 array.

    Cached: it depends only on the size and the palette, neither of which
    changes per frame, and the shading maths below is far too expensive to
    redo 30 times a second. The caller must not mutate the result.
    """
    ys, xs = np.mgrid[0:size, 0:size]
    # Projection onto the (1, 1) diagonal, normalized to 0-1.
    t = (xs + ys) / (2 * (size - 1))

    stops = np.linspace(0.0, 1.0, len(colors))
    channels = [
        np.interp(t, stops, [c[i] for c in colors]) for i in range(3)
    ]
    rgb = np.stack(channels, axis=-1)

    # --- Spherical shading -------------------------------------------------
    # A flat diagonal ramp reads as a sticker. Treating the blob as a lit
    # sphere is what makes it look three-dimensional, as in the reference
    # design. Reconstruct a surface normal from the distance to the centre
    # (z = sqrt(1 - x² - y²), the front hemisphere of a unit sphere) and
    # light it with a simple Lambert term plus a specular lobe.
    nx = (xs / (size - 1)) * 2 - 1
    ny = (ys / (size - 1)) * 2 - 1
    r2 = np.clip(nx**2 + ny**2, 0, 1)
    nz = np.sqrt(1 - r2)

    lx, ly, lz = LIGHT_DIRECTION
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    lambert = np.clip((nx * lx + ny * ly + nz * lz) / norm, 0, 1)

    # Ambient floor keeps the unlit side coloured rather than black.
    shading = AMBIENT + (1 - AMBIENT) * lambert
    rgb = rgb * shading[..., None]

    # Specular: a tight highlight where the surface faces the light most
    # directly — the wet, glassy dot that sells the sphere.
    specular = lambert**SPECULAR_SHARPNESS * SPECULAR_STRENGTH
    rgb = rgb + (255 - rgb) * specular[..., None]

    # Rim light on the far edge, the way a real object picks up light from
    # its surroundings. Without it the blob's silhouette dies into the
    # background instead of reading as a curved edge.
    rim = np.clip(1 - nz, 0, 1) ** RIM_SHARPNESS * RIM_STRENGTH
    rgb = rgb + (255 - rgb) * rim[..., None]

    return np.clip(rgb, 0, 255).astype(np.uint8)


def render_alpha(size: int, t: float, level: float = 0.0) -> Image.Image:
    """The blob's silhouette *and* glow as an `size` x `size` alpha mask
    ("L" mode), at time `t` and mic `level`.

    Split from color deliberately. This is the expensive half — polygon fill,
    gaussian blur and a supersampled downscale, ~18ms — and it depends only
    on time and level, never on the palette. So a loop of these is rendered
    once up front and reused for every state, instead of re-rendering
    whenever the color changes. See `compose`.
    """
    hi = size * SUPERSAMPLE
    blob_extent = int(hi * BLOB_INSET)
    offset = (hi - blob_extent) // 2

    mask = Image.new("L", (hi, hi), 0)
    points = blob_points(blob_extent, blob_extent, t=t, level=level, n_points=180)
    ImageDraw.Draw(mask).polygon([(x + offset, y + offset) for x, y in points], fill=255)

    # The glow is the silhouette itself, blurred well past its own edge, so
    # it always follows the blob's shape as it morphs.
    glow = mask.filter(ImageFilter.GaussianBlur(hi * GLOW_BLUR_RATIO))
    alpha = np.maximum(
        np.asarray(mask, dtype=np.float32),
        np.asarray(glow, dtype=np.float32) * GLOW_ALPHA,
    )

    # Downsampling the supersampled mask is what turns the hard polygon edge
    # into a smooth one.
    return Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), mode="L").resize(
        (size, size), Image.LANCZOS
    )


def compose(alpha: Image.Image, colors: "tuple[tuple[int, int, int], ...]") -> Image.Image:
    """Combines a pre-rendered alpha mask with a gradient through `colors`
    into an RGBA frame. Cheap enough to run every frame — it's a gradient
    lookup and an array stack, with none of `render_alpha`'s cost."""
    size = alpha.size[0]
    rgba = np.dstack([_gradient(size, colors), np.asarray(alpha)])
    return Image.fromarray(rgba.astype(np.uint8), mode="RGBA")


def render_blob(
    size: int,
    t: float,
    level: float,
    colors: "tuple[tuple[int, int, int], ...]",
) -> Image.Image:
    """One complete RGBA frame — convenience wrapper over `render_alpha` +
    `compose`, for tests and one-off rendering. The animation loop uses the
    two halves separately so it never pays `render_alpha`'s cost per frame.

    Fully transparent everywhere the blob and its glow aren't — there is no
    background, which is the entire point.
    """
    return compose(render_alpha(size, t, level), colors)
