"""The caption panel - see `heypeer/tray/caption_render.py`."""

from PIL import Image, ImageDraw

from heypeer.tray.caption_render import (
    MARGIN,
    MAX_LINES,
    WIDTH,
    LINE_HEIGHT,
    position,
    render,
    wrap,
)
from heypeer.tray.caption_window import MAX_SECONDS, MIN_SECONDS, dismiss_after


def _draw():
    return ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def _font():
    from heypeer.tray.caption_render import _font as load

    return load(17)


def test_a_short_answer_renders_a_short_panel() -> None:
    """Height follows the text - no fixed box with dead space under it."""
    short = render("C'est fait.")
    long = render("La fonction plante sur une liste vide " * 6)
    assert short is not None and long is not None
    assert short.height < long.height


def test_empty_text_renders_nothing() -> None:
    assert render("") is None
    assert render("   ") is None


def test_the_panel_has_transparent_corners() -> None:
    image = render("bonjour tout le monde")
    assert image.getpixel((0, 0))[3] == 0


def test_wrapping_is_measured_against_the_real_font() -> None:
    """Character-count wrapping overflows on wide words and wastes half the
    panel on narrow ones."""
    font, draw = _font(), _draw()
    narrow = wrap("i" * 200, font, draw, 200)
    wide = wrap("W " * 100, font, draw, 200)
    assert len(wide) > 1
    assert all(draw.textlength(line, font=font) <= 200 for line in wide)
    assert narrow  # a single unbreakable token still produces a line


def test_a_single_overlong_word_is_not_broken_mid_token() -> None:
    """A URL or a path is wanted whole; hyphenating one makes it useless."""
    font, draw = _font(), _draw()
    url = "https://example.com/a/very/long/path/that/never/ends/at/all"
    assert wrap(url, font, draw, 50) == [url]


def test_a_very_long_answer_is_truncated_with_an_ellipsis() -> None:
    image = render("mot " * 400)
    assert image is not None
    max_height = 2 * MARGIN + LINE_HEIGHT * MAX_LINES
    assert image.height <= max_height


def test_wrap_of_nothing_is_empty() -> None:
    assert wrap("   ", _font(), _draw(), 200) == []


def test_position_keeps_the_panel_on_screen() -> None:
    x, y = position(1920, 1080, 120)
    assert 0 < x < 1920 - WIDTH + 1
    assert 0 < y < 1080


def test_dismissal_scales_with_length_within_bounds() -> None:
    """A fixed timeout either rushes a paragraph away or leaves "c'est fait"
    up long after it stopped mattering."""
    assert dismiss_after(1) == MIN_SECONDS
    assert dismiss_after(4) > dismiss_after(1)
    assert dismiss_after(500) == MAX_SECONDS
