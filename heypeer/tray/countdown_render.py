"""One frame of the countdown pill - the visible half of timers.

Rendered as an RGBA image and pushed through `overlay.py`, exactly like the
blob: same per-pixel-alpha compositing, same reasons (see that module's
docstring for why a browser engine was abandoned for this). Keeping the
drawing here, returning an image and touching no window, is also what makes
it testable in this sandbox - there is no display attached, and a renderer
that owned its own window could not be checked at all.

## The design

A dark rounded pill, sized to its text, with the remaining time as the one
thing that reads at a glance and the label under it in a quieter grey. The
progress arc around the digits is the part that earns its place: it turns
"4:37" into something you can judge without reading, which is the whole
point of a glanceable timer. It drains clockwise from full, and shifts from
the blob's cyan to amber to red as the last fifth runs out - colour carrying
urgency, not decoration.

Colours are taken from `blob_render`'s palette on purpose: the countdown and
the indicator are the same assistant, and two unrelated accent colours on
one screen would read as two apps.
"""

import math

from PIL import Image, ImageDraw

from heypeer.tray.blob_render import PALETTE_CYAN

# Rendered at 2x and downsampled - PIL has no antialiased arc or rounded
# rectangle, so the only way to get clean curves is to draw them big and
# shrink. Cheap enough at this size, and the difference is very visible.
SUPERSAMPLE = 2

WIDTH = 226
HEIGHT = 92
RADIUS = 20  # pill corner radius

DIAL_SIZE = 56
DIAL_THICKNESS = 5

BACKGROUND = (18, 22, 30, 236)
BORDER = (255, 255, 255, 28)
TRACK = (255, 255, 255, 34)  # the un-drained part of the arc
TEXT = (245, 248, 252, 255)
LABEL = (150, 162, 178, 255)

URGENT = (248, 113, 113)  # last 10%
WARNING = (251, 191, 36)  # last 20%

# Below this fraction remaining, the arc turns amber, then red. Chosen so a
# 10-minute timer warns with two minutes left, which is long enough to act
# on and short enough to mean something.
WARNING_FRACTION = 0.2
URGENT_FRACTION = 0.1


def arc_color(fraction_remaining: float) -> "tuple[int, int, int]":
    """The dial's colour for a given fraction of time left. Split out
    because it is the piece worth asserting on in a test - reading a colour
    back off rendered pixels tests PIL more than it tests this."""
    if fraction_remaining <= URGENT_FRACTION:
        return URGENT
    if fraction_remaining <= WARNING_FRACTION:
        return WARNING
    return PALETTE_CYAN


def _font(size: int):
    """A real font if one can be found, PIL's bitmap default otherwise.

    DejaVu ships with PIL itself, so this normally succeeds everywhere
    including this Linux sandbox; the fallback exists because the default
    font cannot be scaled and would make the countdown unreadable rather
    than merely plain."""
    from PIL import ImageFont

    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(clock_text: str, label: str, fraction_remaining: float) -> Image.Image:
    """One countdown frame.

    `clock_text` is already formatted ("4:37" - see
    `executor/reminders.format_clock`); this module does no time arithmetic
    of its own, so what is drawn and what is spoken cannot drift apart.
    `fraction_remaining` drives the dial, clamped so a timer that has just
    fired, or one whose duration was zero, still renders something sane.
    """
    fraction = min(1.0, max(0.0, fraction_remaining))
    s = SUPERSAMPLE
    image = Image.new("RGBA", (WIDTH * s, HEIGHT * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        [(0, 0), (WIDTH * s - 1, HEIGHT * s - 1)],
        radius=RADIUS * s,
        fill=BACKGROUND,
        outline=BORDER,
        width=max(1, s),
    )

    # Dial, vertically centred on the left.
    pad = 20 * s
    dial_box = [
        (pad, (HEIGHT * s - DIAL_SIZE * s) // 2),
        (pad + DIAL_SIZE * s, (HEIGHT * s + DIAL_SIZE * s) // 2),
    ]
    # 0->359.9 rather than 0->360: PIL draws nothing for a zero-length span
    # and treats the two endpoints as identical, leaving a visible notch
    # where the track should close on itself.
    draw.arc(dial_box, start=0, end=359.9, fill=TRACK, width=DIAL_THICKNESS * s)
    if fraction > 0:
        # -90 puts the start at twelve o'clock; draining clockwise reads as
        # time running out, where counting up would read as progress made.
        draw.arc(
            dial_box,
            start=-90,
            end=-90 + min(359.9, 360 * fraction),
            fill=arc_color(fraction) + (255,),
            width=DIAL_THICKNESS * s,
        )

    text_x = pad + DIAL_SIZE * s + 16 * s
    if label:
        # With a label, the two stack; the clock keeps the visual weight.
        draw.text((text_x, HEIGHT * s // 2 - 22 * s), clock_text, font=_font(30 * s), fill=TEXT)
        draw.text((text_x, HEIGHT * s // 2 + 8 * s), _elide(label, 18), font=_font(15 * s), fill=LABEL)
    else:
        clock_font = _font(34 * s)
        bbox = draw.textbbox((0, 0), clock_text, font=clock_font)
        draw.text(
            (text_x, (HEIGHT * s - (bbox[3] - bbox[1])) // 2 - bbox[1]),
            clock_text,
            font=clock_font,
            fill=TEXT,
        )

    return image.resize((WIDTH, HEIGHT), Image.LANCZOS)


def _elide(text: str, limit: int) -> str:
    """Long labels are cut rather than wrapped: the pill is a fixed size, and
    a timer called "les pates pour ce soir avec les invites" should still
    show its digits rather than reflowing the whole window."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def position(screen_width: int, screen_height: int, margin: int = 24) -> "tuple[int, int]":
    """Top-right, below the usual notification area. Away from the blob,
    which sits by the cursor, so the two never overlap."""
    return (screen_width - WIDTH - margin, margin + 48)
