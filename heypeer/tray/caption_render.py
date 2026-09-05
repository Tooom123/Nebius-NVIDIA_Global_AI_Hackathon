"""One frame of the caption panel - what Hey Peer just said, on screen.

## Why show text at all, for a voice assistant

Speech is gone the moment it is spoken. That is fine for "c'est fait" and
bad for everything with content in it: a clipboard read back, a code
diagnosis, a summary of a document, what a video just said. The user cannot
re-read it, cannot copy the filename out of it, and if they missed a word
the only recovery is to ask again and listen harder.

It also covers the case voice cannot: a machine on mute, a shared office, a
headset that is not plugged in. The answer still arrives.

## Why only some answers

Captioning every "j'ouvre Spotify" would put a panel on screen dozens of
times a day to repeat one word the user already heard. The caller decides;
see `main.py`'s `_should_caption`, which shows the ones with something to
re-read and skips the acknowledgements.

Rendered as an image and pushed through `overlay.py`, same as the blob and
the countdown - see `countdown_render.py` for why the drawing lives in its
own module with no window in it.
"""

from PIL import Image, ImageDraw

from heypeer.tray.blob_render import PALETTE_CYAN

SUPERSAMPLE = 2

WIDTH = 460
MARGIN = 22
LINE_HEIGHT = 26
FONT_SIZE = 17
MAX_LINES = 8  # past this it is a document, not a spoken answer

BACKGROUND = (18, 22, 30, 240)
BORDER = (255, 255, 255, 28)
TEXT = (238, 243, 249, 255)
ACCENT = PALETTE_CYAN + (255,)

# Width of the accent bar down the left edge. It is what makes the panel
# read as Hey Peer's rather than as a generic system toast, and it reuses
# the blob's own colour for exactly that reason.
ACCENT_BAR = 3


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(text: str, font, draw, max_width: int) -> "list[str]":
    """Greedy word wrap measured against the actual font.

    Measured rather than estimated from a character count: the panel is
    proportional-font text, where "iiii" and "WWWW" are wildly different
    widths, and a character-count wrap overflows on one and wastes half the
    panel on the other.

    A single word longer than the line (a URL, a long path) is left to
    overflow rather than broken mid-word - it is usually something the user
    wants to read as one token, and hyphenating a path makes it useless.
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


def render(text: str) -> "Image.Image | None":
    """The caption panel, or None if there is nothing worth showing.

    Height follows the text: a one-line answer gets a one-line panel, not a
    fixed box with dead space under it.
    """
    text = (text or "").strip()
    if not text:
        return None

    s = SUPERSAMPLE
    font = _font(FONT_SIZE * s)
    # A scratch surface to measure against - textlength needs a drawing
    # context, and the real one cannot exist until the height is known.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    usable = (WIDTH - 2 * MARGIN - ACCENT_BAR) * s
    lines = wrap(text, font, measure, usable)
    if not lines:
        return None
    truncated = len(lines) > MAX_LINES
    lines = lines[:MAX_LINES]
    if truncated:
        lines[-1] = lines[-1].rstrip(" .,") + "…"

    height = 2 * MARGIN + LINE_HEIGHT * len(lines)
    image = Image.new("RGBA", (WIDTH * s, height * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [(0, 0), (WIDTH * s - 1, height * s - 1)],
        radius=14 * s,
        fill=BACKGROUND,
        outline=BORDER,
        width=max(1, s),
    )
    draw.rounded_rectangle(
        [(0, 10 * s), (ACCENT_BAR * s, (height - 10) * s)],
        radius=ACCENT_BAR * s,
        fill=ACCENT,
    )

    y = MARGIN * s
    for line in lines:
        draw.text(((MARGIN + ACCENT_BAR) * s, y), line, font=font, fill=TEXT)
        y += LINE_HEIGHT * s

    return image.resize((WIDTH, height), Image.LANCZOS)


def position(screen_width: int, screen_height: int, panel_height: int, margin: int = 24) -> "tuple[int, int]":
    """Bottom-right, above the taskbar. Away from the countdown (top-right)
    and the blob (by the cursor), so all three can be on screen at once
    without stacking on top of each other."""
    return (screen_width - WIDTH - margin, screen_height - panel_height - margin - 48)
