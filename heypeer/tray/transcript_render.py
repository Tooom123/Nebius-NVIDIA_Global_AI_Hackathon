"""The live transcript - the conversation, one line at a time, typed out.

## What replaced what

There was a caption panel in the bottom-right corner (`caption_render.py`),
showing whatever Hey Peer had just said. The user asked for it to go: a
panel in a corner is a notification, and notifications are things you
dismiss. This is the opposite - the conversation appears across the top of
the screen, in one fixed place, and is gone as soon as it stops being
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
DejaVu, which ships with Pillow so there is always something. Outlined in
black all the way round, since it is composited over whatever the user
happens to have open and cannot assume a dark background.
"""

from PIL import Image, ImageDraw

WIDTH = 520
MARGIN = 26
LINE_HEIGHT = 34
FONT_SIZE = 23
MAX_LINES = 4

TEXT = (255, 255, 255, 255)
# A true outline, drawn all the way round each glyph, rather than the offset
# drop shadow this had first. A shadow only darkens one side, so white text
# over a light window lost its top-left edge; an outline holds the letters
# on any background, which is what this needs - it sits over whatever the
# user happens to have open.
OUTLINE = (0, 0, 0, 235)
OUTLINE_WIDTH = 3

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
        # Pillow's own stroke, rather than drawing the text several times at
        # offsets: it strokes the real glyph outline, so corners and thin
        # stems stay clean where eight offset copies leave notches.
        draw.text(
            (MARGIN * s, y), line, font=font, fill=TEXT,
            stroke_width=OUTLINE_WIDTH * s, stroke_fill=OUTLINE,
        )
        y += LINE_HEIGHT * s

    return image.resize((WIDTH, height), Image.LANCZOS)


# How far in from the screen's edge the panel sits. Clear of the border
# glow's band so the text is never read through it.
TOP_MARGIN = 26
GLOW_CLEARANCE = 96


def position(screen_width: int, screen_height: int, panel_height: int) -> "tuple[int, int]":
    """Top of the screen, just right of centre, at the user's request.

    Fixed rather than following the blob. Beside a cursor-following blob the
    panel moved while it was being read, and near a screen edge it had to
    flip sides mid-sentence; anchored at the top it is always in the same
    place, which is what makes it glanceable.

    Inset by `GLOW_CLEARANCE` so it clears the border glow's band - white
    text read through a coloured glow is legible in a screenshot and much
    less so in motion.
    """
    x = min(screen_width // 2 + GLOW_CLEARANCE, screen_width - WIDTH - GLOW_CLEARANCE)
    return (max(GLOW_CLEARANCE, x), TOP_MARGIN)
