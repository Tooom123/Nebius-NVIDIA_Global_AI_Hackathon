"""The cursor that flies to a control and clicks it.

## Why a visible cursor at all

Hey Peer's difference from every "AI that sees your screen" is that it
*acts*. That difference is invisible: a file moves, a setting changes, and
the user is told afterwards in a sentence. A cursor that travels to the
control and presses it makes the acting itself the thing you watch.

## The design, after HeyClicky

The first version was pixel art - a hand-placed 12x12 arrow, drawn with
NEAREST resampling. The user asked for something cleaner and more styled,
pointing at HeyClicky, so this follows what their open-source overlay
actually does (read from `OverlayWindow.swift`, not guessed):

* A small solid equilateral triangle - not an arrow outline - with a soft
  glow in its own colour. Small on purpose: it reads as a *companion* to
  the pointer rather than a second pointer competing with it.
* At rest it leans to -35 degrees, the angle of a system cursor, so it is
  recognisably a pointer without being one.
* In flight it **turns to face where it is going** - its heading is the
  tangent of the curve - so the tip leads the motion. This is the single
  detail that makes it read as something travelling rather than something
  being dragged.
* It swells to 1.3x at the top of the arc and settles back on landing, and
  its glow brightens while it moves.
* The path is a quadratic Bezier bowed upward, eased slow-fast-slow, and
  its duration scales with distance between 0.6 and 1.4 seconds - a short
  hop is quick, a cross-screen flight is allowed to be a moment.

Two differences from Clicky, both because this cursor *clicks* where
theirs only points: the tip, not the centre, sits on the target coordinate,
so the press lands where the triangle visibly points; and the press is
marked by a ring that contracts onto the tip.

Rendered at 4x and downsampled with LANCZOS - the reverse of the pixel-art
version, whose whole point was hard edges. A triangle this small with
aliased edges looks like a rendering bug.

## Colour

Red (255, 0, 0) by default - the user's choice, kept through the redesign -
and changed at onboarding through `set_color`.
"""

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

DEFAULT_COLOR = (255, 0, 0)
_color = DEFAULT_COLOR

# Side of the triangle, in screen pixels. Clicky's is 16pt, which is 32
# physical pixels on a Retina Mac; 18 is the equivalent presence on a
# 1080p Windows screen without becoming a second mouse pointer.
TRIANGLE_SIZE = 18

# The surface the triangle is drawn on. Large enough for the triangle at
# its 1.3x flight scale pointing in any direction from the centre, plus the
# glow around it, so nothing is ever clipped at the window edge.
SURFACE = 84

SUPERSAMPLE = 4

# The resting lean - a system cursor's angle. Degrees clockwise from
# tip-up, which is also how the heading in flight is expressed.
REST_ANGLE = -35.0

GLOW_RADIUS = 7.0
GLOW_STRENGTH = 0.85

# The press ring: starts this far out and contracts onto the tip.
RING_MAX_RADIUS = 22
RING_WIDTH = 2.5

# Flight timing, from Clicky's own constants.
FLIGHT_MIN_SECONDS = 0.6
FLIGHT_MAX_SECONDS = 1.4
FLIGHT_PIXELS_PER_SECOND = 800.0
ARC_FRACTION = 0.2
ARC_MAX_PIXELS = 80.0
FLIGHT_SCALE_PEAK = 0.3


def set_color(rgb: "tuple[int, int, int]") -> None:
    """Sets the cursor's colour - what onboarding calls once the user has
    picked one. Clears the frame cache, since every cached frame is in the
    old colour."""
    global _color
    _color = tuple(max(0, min(255, int(c))) for c in rgb[:3])
    _cached_frame.cache_clear()


def color() -> "tuple[int, int, int]":
    return _color


def triangle_points(
    cx: float, cy: float, angle_deg: float, size: float
) -> "list[tuple[float, float]]":
    """The triangle's three corners with its *tip* at `(cx, cy)`.

    The tip rather than the centroid, because this cursor clicks: the press
    lands on the target coordinate, so the visible point of the triangle has
    to be on it. `angle_deg` is clockwise from tip-up.
    """
    a = math.radians(angle_deg)
    # Heading the tip points along, in image coordinates (y down).
    hx, hy = math.sin(a), -math.cos(a)
    # Perpendicular, for the base.
    px, py = -hy, hx
    height = size * math.sqrt(3) / 2
    bx, by = cx - hx * height, cy - hy * height
    half = size / 2
    return [(cx, cy), (bx + px * half, by + py * half), (bx - px * half, by - py * half)]


def render(
    angle: float = REST_ANGLE, scale: float = 1.0, glow: float = 1.0, press: float = 0.0
) -> Image.Image:
    """One cursor frame, tip at the centre of the surface.

    `angle` is the heading in degrees (clockwise from tip-up), `scale` the
    flight swell, `glow` how bright the halo is, and `press` 0..1 the
    contracting click ring. Values are rounded before rendering so a flight
    reuses frames from the cache rather than blurring sixty new ones a
    second.
    """
    return _cached_frame(
        round(angle),
        round(max(0.5, min(2.0, scale)), 2),
        round(max(0.0, min(2.0, glow)), 2),
        round(max(0.0, min(1.0, press)), 2),
    ).copy()


@lru_cache(maxsize=512)
def _cached_frame(angle: int, scale: float, glow: float, press: float) -> Image.Image:
    s = SUPERSAMPLE
    size = SURFACE * s
    centre = size / 2
    rgb = _color

    points = triangle_points(centre, centre, angle, TRIANGLE_SIZE * scale * s)

    # Glow: the triangle's own silhouette, blurred, in its own colour. A
    # coloured halo rather than a drop shadow - Clicky's shadow is the
    # cursor colour at full radius, which is what makes it look lit rather
    # than pasted on.
    glow_layer = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glow_layer).polygon(points, fill=int(255 * GLOW_STRENGTH * min(glow, 1.0)))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(GLOW_RADIUS * s * max(glow, 0.3)))

    image = Image.new("RGBA", (size, size), rgb + (0,))
    image.putalpha(glow_layer)

    draw = ImageDraw.Draw(image)
    if press > 0:
        radius = RING_MAX_RADIUS * s * (1.0 - press)
        if radius > s:
            draw.ellipse(
                [(centre - radius, centre - radius), (centre + radius, centre + radius)],
                outline=rgb + (int(235 * press),),
                width=max(1, int(RING_WIDTH * s)),
            )

    draw.polygon(points, fill=rgb + (255,))

    return image.resize((SURFACE, SURFACE), Image.LANCZOS)


def flight_seconds(start: "tuple[int, int]", end: "tuple[int, int]") -> float:
    """How long a flight takes. Scales with distance, clamped - a short hop
    is quick and a cross-screen flight is allowed to be a moment."""
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    return min(max(distance / FLIGHT_PIXELS_PER_SECOND, FLIGHT_MIN_SECONDS), FLIGHT_MAX_SECONDS)


def flight_frames(
    start: "tuple[int, int]", end: "tuple[int, int]", fps: int = 60
) -> "list[tuple[int, int, float, float, float]]":
    """Every frame of a flight, as `(x, y, angle, scale, glow)`.

    A quadratic Bezier bowed upward, eased slow-fast-slow, with the heading
    taken from the curve's tangent so the tip leads. The last frame is
    exactly `end`, however the arc bows - this is a click coordinate.
    """
    frames_total = max(2, int(flight_seconds(start, end) * fps))
    x0, y0 = start
    x2, y2 = end
    distance = math.hypot(x2 - x0, y2 - y0)
    if distance < 1:
        return [(x2, y2, REST_ANGLE, 1.0, 1.0)] * frames_total

    arc = min(distance * ARC_FRACTION, ARC_MAX_PIXELS)
    x1 = (x0 + x2) / 2
    y1 = (y0 + y2) / 2 - arc  # upward, in screen coordinates

    frames = []
    for i in range(1, frames_total + 1):
        linear = i / frames_total
        t = linear * linear * (3 - 2 * linear)
        u = 1 - t
        x = u * u * x0 + 2 * u * t * x1 + t * t * x2
        y = u * u * y0 + 2 * u * t * y1 + t * t * y2
        tx = 2 * u * (x1 - x0) + 2 * t * (x2 - x1)
        ty = 2 * u * (y1 - y0) + 2 * t * (y2 - y1)
        # atan2 gives 0 for rightward motion; the tip points up at 0, so a
        # quarter turn lines them up.
        angle = math.degrees(math.atan2(ty, tx)) + 90.0
        pulse = math.sin(linear * math.pi)
        frames.append((round(x), round(y), angle, 1.0 + pulse * FLIGHT_SCALE_PEAK, 1.0 + pulse * 0.6))

    x, y, angle, _, _ = frames[-1]
    frames[-1] = (x2, y2, angle, 1.0, 1.0)
    return frames
