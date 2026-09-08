"""The live transcript beside the blob - one line at a time, typed out.

## What replaced what

There was a caption panel in the bottom-right corner (`caption_render.py`),
showing whatever Hey Peer had just said. The user asked for it to go: a
panel in a corner is a notification, and notifications are things you
dismiss. This is the opposite - the conversation appears *beside the blob*,
where the user is already looking, and is gone as soon as it stops being
current.

## Why one side at a time

The whole exchange is transcribed, but never accumulated. What the user is
saying appears word by word as they say it; when Hey Peer answers, that is
cleared and the reply types itself in the same place. So the panel always
holds exactly one thing - the present - and never becomes a log to read.

A stacked transcript would grow, need scrolling, and turn a glance into
reading. This is meant to be understood without being read.

## The typing

Characters appear progressively rather than the line arriving whole. For
the user's own words that mirrors dictation, which is the convention every
voice interface uses because it proves the machine is keeping up. For Hey
Peer's it paces the text against the speech, so the eye is not three
sentences ahead of the voice.

Rendering is by character count rather than by timer: the caller advances
`revealed`, so the same frame is reproducible and testable, and the speed
lives with whatever owns the clock.

## Type

Helvetica bold white, at the user's request. `_font` walks the real
Helvetica names first and falls back through Arial - metrically compatible,
and on Windows the substitute Helvetica usually resolves to anyway - then
DejaVu, which ships with Pillow so there is always something. No outline,
no shadow beyond a soft one: the glow behind it does the separating.
"""

from PIL import Image, ImageDraw

WIDTH = 520
MARGIN = 26
LINE_HEIGHT = 34
FONT_SIZE = 23
MAX_LINES = 4

TEXT = (255, 255, 255, 255)
# A soft dark backing rather than a panel: enough to keep white legible over
# a bright window, not enough to read as a box with edges. The corner panel
# this replaces had a border and a fill, which is what made it look like a
# notification.
SHADOW = (0, 0, 0, 150)
SHADOW_OFFSET = 2

SUPERSAMPLE = 2


def _font(size: int):
    """Helvetica bold if the system has it, else the closest thing.

    Helvetica proper is rare on Windows; Arial is metrically compatible and
    is what Windows substitutes anyway, so the fallback changes the shapes
    slightly and nothing about the layout. DejaVu last because it ships with
    Pillow - there is always something to draw with.
    """
    from PIL import ImageFont

    for name in (
        "Helvetica-Bold.ttf", "HelveticaBold.ttf", "Helvetica.ttc",
        "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(text: str, font, draw, max_width: int) -> "list[str]":
    """Greedy word wrap, measured against the real font.

    Measured rather than counted: this is proportional type, where "iiii"
    and "WWWW" are wildly different widths, so a character count overflows
    on one and wastes half the line on the other.
    """
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def visible_text(text: str, revealed: int) -> str:
    """The first `revealed` characters. Negative means all of it, which is
    what a caller that does not want the typing effect passes."""
    if revealed < 0:
        return text
    return text[:revealed]


def render(text: str, revealed: int = -1) -> "Image.Image | None":
    """The transcript as it currently stands, or None if there is nothing
    to show.

    `revealed` is how many characters have appeared so far. The image is
    sized to the text, so a one-line utterance is a one-line image rather
    than a fixed box with dead space under it.
    """
    shown = visible_text(text or "", revealed).rstrip()
    if not shown:
        return None

    s = SUPERSAMPLE
    font = _font(FONT_SIZE * s)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    usable = (WIDTH - 2 * MARGIN) * s

    lines = wrap(shown, font, measure, usable)
    if not lines:
        return None
    # Keep the *last* lines rather than the first: while text is being typed
    # out the end is what just changed, and dropping it would freeze the
    # panel at the start of a long sentence.
    if len(lines) > MAX_LINES:
        lines = lines[-MAX_LINES:]

    height = 2 * MARGIN + LINE_HEIGHT * len(lines)
    image = Image.new("RGBA", (WIDTH * s, height * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    y = MARGIN * s
    for line in lines:
        draw.text(
            ((MARGIN + SHADOW_OFFSET) * s, y + SHADOW_OFFSET * s),
            line, font=font, fill=SHADOW,
        )
        draw.text((MARGIN * s, y), line, font=font, fill=TEXT)
        y += LINE_HEIGHT * s

    return image.resize((WIDTH, height), Image.LANCZOS)


def position(
    blob_x: int, blob_y: int, blob_size: int, panel_height: int, screen_width: int
) -> "tuple[int, int]":
    """Where to put the panel, given where the blob is.

    Beside it, vertically centred on it, and on whichever side has room -
    the blob follows the cursor, so a panel fixed to its right would run off
    the screen every time the user works near the right edge.
    """
    gap = 12
    right = blob_x + blob_size + gap
    y = blob_y + (blob_size - panel_height) // 2
    if right + WIDTH <= screen_width:
        return (right, y)
    return (max(0, blob_x - WIDTH - gap), y)
