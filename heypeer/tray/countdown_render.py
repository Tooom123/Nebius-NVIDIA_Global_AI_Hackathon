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

from heypeer.tray.blob_render import APPLE_BLUE, APPLE_ORANGE, APPLE_PINK, APPLE_PURPLE

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

# The dial's own colours, from Apple Intelligence's palette rather than the
# old cyan/amber/red: the countdown and the blob are the same assistant, and
# a timer in unrelated colours read as a different application's widget.
# Urgency still reads, because the palette runs warm to cool - so counting
# *down* it travels blue -> purple -> pink -> orange, which is the same
# calm-to-alarming direction the old ramp had.
URGENT = APPLE_ORANGE   # last 10%
WARNING = APPLE_PINK    # last 20%
CALM = APPLE_BLUE
MID = APPLE_PURPLE

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
    # A third step rather than one flat colour for the whole first 80%: the
    # dial now moves through the palette as it drains instead of sitting on
    # one hue and then jumping, which is what made the old one read as a
    # progress bar rather than as part of Hey Peer.
    if fraction_remaining <= 0.5:
        return MID
    return CALM


def _font(size: int):
    """Helvetica bold, the same face as the transcript.

    Shared deliberately: two of Hey Peer's own surfaces in two different
    typefaces reads as two applications. `transcript_render._font` owns the
    fallback chain (Helvetica, then Arial, then DejaVu which ships with
    Pillow), so there is one list to keep right rather than two."""
    from heypeer.tray.transcript_render import _font as helvetica

    return helvetica(size)


# The "stop" button shown once a timer has fired, in place of the dial. Its
# rectangle is exported so the window can hit-test a click against it - the
# drawing and the clickable area must come from one number, or the button
# moves without its hit area following.
STOP_SIZE = 52


def stop_button_rect() -> "tuple[int, int, int, int]":
    """`(left, top, right, bottom)` of the stop button inside the pill, in
    pill-local pixels. Same geometry the ringing frame draws."""
    pad = 20
    top = (HEIGHT - STOP_SIZE) // 2
    return (pad, top, pad + STOP_SIZE, top + STOP_SIZE)


def render(
    clock_text: str, label: str, fraction_remaining: float, ringing: bool = False
) -> Image.Image:
    """One countdown frame.

    `clock_text` is already formatted ("4:37" - see
    `executor/reminders.format_clock`); this module does no time arithmetic
    of its own, so what is drawn and what is spoken cannot drift apart.
    `fraction_remaining` drives the dial, clamped so a timer that has just
    fired, or one whose duration was zero, still renders something sane.

    `ringing` swaps the dial for a stop button. The alarm replaces the
    countdown in the same place rather than appearing elsewhere: the user
    was already watching this pill, so that is where they will look when it
    goes off.
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

    if ringing:
        return _render_ringing(image, draw, label, s)

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


def _render_ringing(image, draw, label: str, s: int):
    """The fired state: a stop button where the dial was, and what the timer
    was for where the clock was."""
    left, top, right, bottom = (v * s for v in stop_button_rect())

    # Filled circle in the urgent colour, with a square inside it - the
    # universal stop glyph, and legible at this size where a cross or a
    # "muet" label would not be.
    draw.ellipse([(left, top), (right, bottom)], fill=URGENT + (255,))
    inset = (right - left) * 0.32
    draw.rounded_rectangle(
        [(left + inset, top + inset), (right - inset, bottom - inset)],
        radius=int(2 * s),
        fill=(255, 255, 255, 255),
    )

    text_x = right + 16 * s
    shown = _elide(label, 16) if label else ""
    if shown:
        draw.text((text_x, HEIGHT * s // 2 - 22 * s), "C'est l'heure", font=_font(19 * s), fill=TEXT)
        draw.text((text_x, HEIGHT * s // 2 + 4 * s), shown, font=_font(15 * s), fill=LABEL)
    else:
        # Smaller without a label: at 21 the phrase ran past the pill's
        # right edge, which the render showed immediately.
        font = _font(18 * s)
        bbox = draw.textbbox((0, 0), "C'est l'heure", font=font)
        draw.text(
            (text_x, (HEIGHT * s - (bbox[3] - bbox[1])) // 2 - bbox[1]),
            "C'est l'heure", font=font, fill=TEXT,
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
