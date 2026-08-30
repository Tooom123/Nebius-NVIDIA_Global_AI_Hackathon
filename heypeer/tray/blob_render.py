"""Renders the blob to an RGBA image with real per-pixel alpha.

Drawn as an analytic radial field rather than a filled polygon: for every
pixel, its angle gives the outline's radius there, and its distance from the
centre decides whether it is inside the blob, on its soft edge, or in the
surrounding glow.

That replaces a polygon fill at 3x supersample followed by a gaussian blur.
The old approach cost ~18ms a frame, which forced pre-rendering a short loop
of frames and cycling them - the shape then advanced only a few times a
second and the result looked stepped. The field costs a couple of
milliseconds, so every frame can be rendered live at 30fps from continuously
varying parameters, which is what actually makes the motion smooth.
Antialiasing and the glow fall out of the field itself instead of being
approximated by supersampling and blur.

## Why the colour is shaded rather than a gradient

It used to be a radial gradient in *frame* space: a fixed cyan-to-violet ramp
measured from a point near the top left of the bitmap, cached because it
depended on nothing that changed. It was cheap and it was flat - a disc with
a gradient painted on it, which is what the user saw ("bien animé mais
seulement en 2D, je ne perçois pas vraiment de profondeur sphérique").

The colour is now derived from a **surface normal**. The blob is treated as a
sphere whose silhouette is the animated outline: at each pixel, its distance
from the centre relative to the outline gives how far around the ball that
point sits, and from that a normal pointing out of the surface toward the
viewer. Everything else follows from lighting that normal:

* **Diffuse** - the hue itself follows the light. Cyan where the light hits
  square on, through blue, to violet where it grazes. The ramp therefore
  wraps around the form instead of sliding across the picture, so it stays
  correct as the outline deforms.
* **Specular** - a tight Blinn-Phong highlight up and to the left. A small
  hard bright spot is the single strongest cue that a surface is curved and
  glossy.
* **Rim / Fresnel** - the silhouette lights up where the surface turns away
  from the viewer, which is what makes a ball read as a ball rather than a
  disc, and what carries the volume out into the halo.
* **Ambient occlusion** - the mid-rim is darkened before the rim light is
  added, so the form has a dark shoulder between its lit front and its
  glowing edge. Without it the two run together and it flattens out again.

The halo outside the silhouette is shaded by the same lighting, so it is cool
on the lit side and violet on the shadowed one - a coloured volume bleeding
light rather than a uniform ring.

Output is fully transparent wherever the blob and its glow aren't; there is
no background of any kind (see `overlay.py` for why that matters).
"""

import math
from functools import lru_cache

import numpy as np
from PIL import Image

PALETTE_CYAN = (125, 211, 252)
PALETTE_BLUE = (37, 99, 235)
PALETTE_VIOLET = (124, 58, 237)

# Direction the light comes from, in view space: up and to the left, well in
# front of the blob. y is negative upward because these are image
# coordinates. Normalised at import - the shading maths assumes unit length.
_LIGHT = np.array([-0.40, -0.52, 0.75], dtype=np.float32)
_LIGHT /= np.linalg.norm(_LIGHT)
# Blinn-Phong half vector for a viewer straight ahead at (0, 0, 1).
_HALF = _LIGHT + np.array([0.0, 0.0, 1.0], dtype=np.float32)
_HALF /= np.linalg.norm(_HALF)

# How full the sphere is. A true sphere is 0.5; lower values keep the surface
# facing the viewer over more of the disc and then turn away sharply near the
# silhouette, which reads as a large ball close to the camera rather than a
# small one far away. This is the knob for "depth toward me".
SPHERE_FULLNESS = 0.42

# How far along the cyan-blue-violet ramp a given angle away from the light
# sits. Below 1 it front-loads the ramp, so violet occupies the shadowed side
# properly instead of a crescent at the very bottom.
RAMP_GAMMA = 0.6

# How dark the unlit side gets. Not zero: this is a luminous object, so its
# shadowed side glows violet rather than going black.
AMBIENT = 0.46
# Tightness and strength of the specular highlight. Tight on purpose - a broad
# sheen reads as a gradient, a small hard spot reads as a curved glossy
# surface. The exponent is applied by repeated squaring below rather than
# pow(), i.e. five multiplies instead of a transcendental on every pixel of
# every frame.
SHININESS = 32
SPECULAR = 0.72
# The Fresnel edge: how sharply it is confined to the silhouette, and how much
# it brightens the surface there. The power is an integer so it too costs
# multiplies rather than a pow().
RIM_POWER = 3
RIM_STRENGTH = 0.8
# Depth of the dark shoulder between the lit face and the rim light.
OCCLUSION = 0.30

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
    """Per-pixel offset from the centre, distance and angle. Constant for a
    given frame size, so computed once. float32 throughout: the shading below
    touches every pixel a dozen times and half the memory traffic is most of
    the speed."""
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    centre = (size - 1) / 2
    dx = xs - centre
    dy = ys - centre
    return dx, dy, np.sqrt(dx * dx + dy * dy), np.arctan2(dy, dx)


@lru_cache(maxsize=4)
def _angles(n: int) -> np.ndarray:
    return np.linspace(-math.pi, math.pi, n, endpoint=False, dtype=np.float32)


@lru_cache(maxsize=1)
def _depth_table() -> np.ndarray:
    """`(1 - u^2) ** SPHERE_FULLNESS` for u in 0..1, as a 1024-entry table.

    A fractional power over every pixel of every frame was the single most
    expensive operation in the renderer. It depends only on u, so it is a
    lookup - and at 1024 steps the quantisation is far below what a
    240-pixel-wide shape can show."""
    u = np.linspace(0.0, 1.0, 1024, dtype=np.float32)
    return (1.0 - u * u) ** SPHERE_FULLNESS


@lru_cache(maxsize=1)
def _ramp_curve() -> np.ndarray:
    """`x ** RAMP_GAMMA` as a table - see `_depth_table` for why a table."""
    return np.linspace(0.0, 1.0, 1024, dtype=np.float32) ** RAMP_GAMMA


@lru_cache(maxsize=1)
def _ramp() -> np.ndarray:
    """The cyan-blue-violet ramp as a lookup table, indexed 0-255.

    A table rather than three `np.interp` calls per frame: the ramp is fixed,
    and taking it by index costs a single gather instead of interpolating a
    240x240 array three times."""
    t = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    stops = [0.0, 0.55, 1.0]
    ramp = [PALETTE_CYAN, PALETTE_BLUE, PALETTE_VIOLET]
    return np.stack(
        [np.interp(t, stops, [c[i] for c in ramp]) for i in range(3)], axis=-1
    ).astype(np.float32)


def _shade(dx, dy, dz_scale, u):
    """Lit colour per pixel, given where each one sits on the sphere.

    `u` is the distance from the centre as a fraction of the outline: 0 at
    the middle, 1 at the silhouette, more than 1 out in the halo. Everything
    the eye reads as depth is derived from the normal built here - see the
    module docstring.
    """
    # Height of the sphere's surface above the picture plane. Out in the halo
    # (u > 1) it is flat at zero, which is exactly where a surface turning
    # away from the viewer ends up.
    z = _depth_table()[(np.clip(u, 0.0, 1.0) * 1023).astype(np.int16)]

    nx = dx * dz_scale
    ny = dy * dz_scale
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + z * z + 1e-6)
    nx *= inv
    ny *= inv
    nz = z * inv

    lambert = np.clip(nx * _LIGHT[0] + ny * _LIGHT[1] + nz * _LIGHT[2], 0.0, 1.0)

    # Hue follows the light around the form: cyan facing it, violet grazing.
    # Curved, not linear: the ramp reaches violet well before the light has
    # fully grazed away, so the shadowed side is genuinely violet across its
    # whole width. Linear left the entire form reading as one flat blue with
    # a thin violet crescent, which is exactly the complaint the palette was
    # meant to answer.
    away = np.clip(1.0 - lambert, 0.0, 1.0)
    index = (_ramp_curve()[(away * 1023).astype(np.int16)] * 255.0).astype(np.uint8)
    rgb = _ramp()[index]

    # Darken toward the shadowed side, and again in a band just inside the
    # silhouette so the rim light below has something to stand out against.
    shade = AMBIENT + (1.0 - AMBIENT) * lambert
    depth = np.clip(u, 0.0, 1.0)
    shade = shade * (1.0 - OCCLUSION * depth * depth * depth)
    rgb = rgb * shade[..., None]

    highlight = np.clip(nx * _HALF[0] + ny * _HALF[1] + nz * _HALF[2], 0.0, 1.0)
    h2 = highlight * highlight
    h4 = h2 * h2
    h8 = h4 * h4
    # Confined to the body. Left ungated it also lit the halo, which turned
    # the top of the glow into a grey haze - a highlight is a reflection off
    # a surface, and out there is no surface.
    specular = h8 * h8 * h8 * h8 * SPECULAR * np.clip((1.0 - u) * 8.0, 0.0, 1.0)
    rgb = rgb + (255.0 - rgb) * specular[..., None]

    # A hue-preserving lift, not a blend toward cyan. Blending repainted the
    # silhouette cyan exactly where the palette is most violet - the shadowed
    # edge was being given the colour of the lit one - which is a large part
    # of why the blob still read as uniformly blue. Brightening in place gives
    # a cyan edge where the surface is cyan and a violet edge where it is
    # violet, which is what a glowing volume actually does.
    edge = np.clip(1.0 - nz, 0.0, 1.0)
    rim = edge * edge * edge * RIM_STRENGTH
    rgb = rgb * (1.0 + rim)[..., None]

    return np.clip(rgb, 0.0, 255.0)


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
    dx, dy, distance, theta = _geometry(size)
    outline = (
        np.interp(theta, _angles(len(radii)), radii, period=2 * math.pi) * base_radius
    ).astype(np.float32)

    # Signed distance to the outline: negative inside, positive outside.
    outside = distance - outline

    body = np.clip(0.5 - outside / EDGE_SOFTNESS_PX, 0, 1)
    # Compact support, not an exponential: the halo must reach exactly zero
    # within GLOW_REACH. An exponential only ever approaches zero, so it was
    # still faintly non-zero at the frame border, and a glow cut off by the
    # edge of the bitmap shows as a straight line across it.
    halo = np.clip(1 - np.clip(outside, 0, None) / (base_radius * GLOW_REACH), 0, 1) ** 2
    alpha = np.maximum(body, halo * GLOW_ALPHA * glow) * 255

    # Shading is per-frame now, not cached: it depends on the outline, which
    # is the whole point - the lit face and the rim follow the shape as it
    # deforms instead of a gradient sliding underneath a moving silhouette.
    inv_outline = 1.0 / np.maximum(outline, 1e-3)
    rgb = _shade(dx, dy, inv_outline, distance * inv_outline)

    rgba = np.dstack([rgb, np.clip(alpha, 0, 255)])
    return Image.fromarray(rgba.astype(np.uint8), mode="RGBA")
