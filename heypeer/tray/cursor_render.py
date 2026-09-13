"""The cursor that flies to a control and clicks it - pixel-art, with a trail.

## Why a visible cursor at all

Hey Peer's difference from every "AI that sees your screen" is that it
*acts*. That difference is invisible: a file moves, a setting changes, and
the user is told afterwards in a sentence. A cursor that travels to the
control and presses it makes the acting itself the thing you watch.

It is also the honest way to show an action the user did not perform. A
click that happens with no pointer movement is indistinguishable from the
application doing something on its own; one that arrives, lands and presses
is legible as Hey Peer's doing.

## Not the deleted cursor.py, and not Clicky's

`tray/cursor.py` (deleted, commit 747de11) recoloured the *system* cursor
with `SetSystemCursor` to show auto mode was armed - a status light painted
on the user's own pointer, which fights them for control of it.

Clicky flies a triangle to an element and *points*, so the user knows where
to click. This clicks. Pointing is what an assistant does when it cannot
act.

## The art direction

Pixel art, deliberately. Every other assistant's pointer is a smooth vector
arrow, and a hand-placed 12x12 grid of square pixels reads as a *character*
rather than as a UI affordance - which is the right register for something
that acts on your behalf and that you are meant to notice.

It also sets this apart from the blob, which is the opposite: a soft,
shaded, antialiased sphere. Two different objects that are both Hey Peer,
distinguished by treatment rather than by colour.

The consequence worth stating: this is drawn with NEAREST resampling, never
LANCZOS. Smoothing pixel art is the one thing that would destroy the whole
idea, and it is exactly what every other renderer in this project does.

## Colour

Red (255, 0, 0) by default, chosen by the user, and changed at onboarding.
Not taken from `blob_render`'s palette on purpose: the blob is cyan-violet
and the pointer is meant to be conspicuous against it, not to blend in.
`set_color` is what onboarding calls; everything renders from that.
"""

import math

from PIL import Image, ImageDraw

# The classic pointer, hand-placed on a 12x12 grid. 1 = body, 2 = outline.
# Written out as a picture rather than computed so that changing how it
# looks means editing something that looks like what it draws.
ARROW_PIXELS = [
    "2...........",
    "22..........",
    "212.........",
    "2112........",
    "21112.......",
    "211112......",
    "2111112.....",
    "21111112....",
    "211111112...",
    "2111122222..",
    "211212......",
    "22..212.....",
]

GRID = len(ARROW_PIXELS)

# How many screen pixels one art pixel occupies. 2 puts the arrow at 24px
# tall, which is about a real Windows cursor - 3 made it 36px, and the user
# reported it as "enorme". The blocks stay unmistakably square at 2; going
# to 1 would lose the pixel-art read entirely, which is the point of it.
PIXEL_SCALE = 2

# Drawing surface, in art pixels. Wider than the arrow to leave room for the
# click burst, which extends past the arrowhead on every side.
SURFACE = 26

DEFAULT_COLOR = (255, 0, 0)
OUTLINE = (28, 28, 34, 255)
_color = DEFAULT_COLOR


def set_color(rgb: "tuple[int, int, int]") -> None:
    """Sets the pointer's colour - what onboarding calls once the user has
    picked one. Module-level rather than a parameter threaded through every
    call because it is a preference, not per-frame state."""
    global _color
    _color = tuple(max(0, min(255, int(c))) for c in rgb[:3])


def color() -> "tuple[int, int, int]":
    return _color


# The click burst: four short spokes that shrink inward, drawn in art
# pixels. Contracting rather than expanding - an expanding ripple reads as
# "something happened here", a contracting one as "I am pressing here".
BURST_MAX = 7
BURST_LENGTH = 3


def render(press: float = 0.0, trail: "list[tuple[int, int]] | None" = None) -> Image.Image:
    """One pointer frame, tip at the centre of the surface.

    `press` is 0 at rest and 1 at the instant of the click. `trail` is the
    pointer's recent positions *relative to the current one*, in screen
    pixels, oldest first - drawn as fading blocks behind it.

    Positioning by the tip rather than a corner is deliberate: a click
    coordinate is a point, and every caller would otherwise repeat the same
    offset arithmetic.
    """
    press = min(1.0, max(0.0, press))
    px = PIXEL_SCALE
    size = SURFACE * px
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    origin = (SURFACE // 2) * px

    def block(ax: float, ay: float, fill) -> None:
        """One art pixel at art-grid coordinates, snapped to the grid so
        nothing lands on a half-pixel and blurs the whole effect."""
        x = origin + round(ax) * px
        y = origin + round(ay) * px
        draw.rectangle([(x, y), (x + px - 1, y + px - 1)], fill=fill)

    # Trail first, so the pointer always draws over its own history.
    for i, (dx, dy) in enumerate(trail or []):
        # Older points are fainter and smaller. The oldest is nearly gone,
        # which is what makes it read as a trail rather than as a queue of
        # copies of the cursor.
        # Linear fade, not squared: squaring crushed everything but the
        # newest point and the trail read as two stray dots rather than as
        # motion. The newest blocks are nearly solid, the oldest just
        # visible.
        age = (i + 1) / (len(trail) + 1)
        alpha = int(30 + 195 * age)
        block(dx / px, dy / px, _color + (alpha,))

    if press > 0:
        # Spokes on the four diagonals, contracting toward the tip.
        distance = BURST_MAX * (1.0 - press)
        alpha = int(255 * press)
        # Centred on the arrow's body rather than its tip: centred on the
        # tip the spokes sat up-left of the pointer and read as unrelated
        # sparks beside it instead of a press underneath it.
        cx, cy = 3, 5
        if distance > 0.5:
            for ux, uy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                for step in range(BURST_LENGTH):
                    d = distance + step
                    block(cx + ux * d, cy + uy * d, _color + (alpha,))

    for row, line in enumerate(ARROW_PIXELS):
        for col, cell in enumerate(line):
            if cell == "1":
                block(col, row, _color + (255,))
            elif cell == "2":
                block(col, row, OUTLINE)

    return image


def travel_path(start: "tuple[int, int]", end: "tuple[int, int]", steps: int) -> "list[tuple[int, int]]":
    """Points along a curved path from `start` to `end`.

    Curved and eased rather than straight and linear, because the movement
    exists to be *followed* by an eye that did not know it was coming. A
    pointer that teleports has no travel to follow; one that slides in a
    straight line at constant speed reads as a UI animation rather than as
    something arriving.

    The arc bulges perpendicular to the direction of travel, scaled to the
    distance, so a short hop stays nearly straight and a cross-screen move
    sweeps. Easing is slow-fast-slow: the deceleration onto the target is
    what makes it look like aiming rather than jumping.
    """
    if steps < 2:
        return [end]
    x0, y0 = start
    x1, y1 = end
    dx, dy = x1 - x0, y1 - y0
    distance = math.hypot(dx, dy)
    if distance < 1:
        return [end] * steps
    px, py = -dy / distance, dx / distance
    bulge = min(distance * 0.18, 120)

    path = []
    for i in range(steps):
        t = i / (steps - 1)
        eased = t * t * (3 - 2 * t)
        # Zero at both ends, so the path starts and finishes exactly where
        # asked however large the bulge.
        arch = math.sin(eased * math.pi) * bulge
        path.append((
            round(x0 + dx * eased + px * arch),
            round(y0 + dy * eased + py * arch),
        ))
    return path


TRAIL_LENGTH = 7


def trail_offsets(path: "list[tuple[int, int]]", index: int, length: int = TRAIL_LENGTH) -> "list[tuple[int, int]]":
    """The trail to draw at `path[index]`, as offsets from that point.

    Offsets rather than absolute positions because the pointer's window
    moves with it: the trail has to be drawn inside a surface centred on
    wherever the tip currently is.

    Points that fall outside the drawing surface are dropped rather than
    clamped - a clamped point would pile up against the edge and read as a
    smear stuck to the cursor.
    """
    here = path[index]
    limit = (SURFACE // 2 - 1) * PIXEL_SCALE
    offsets = []
    for point in path[max(0, index - length):index]:
        dx, dy = point[0] - here[0], point[1] - here[1]
        if abs(dx) < limit and abs(dy) < limit:
            offsets.append((dx, dy))
    return offsets
