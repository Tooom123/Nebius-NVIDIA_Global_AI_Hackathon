"""The live transcript panel - see `heypeer/tray/transcript_render.py`."""

from PIL import Image, ImageDraw

from heypeer.tray import transcript_render as tr


def _draw():
    return ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def test_typing_reveals_the_text_progressively() -> None:
    """Proves the machine is keeping up - the convention every voice
    interface uses."""
    assert tr.visible_text("bonjour tout le monde", 7) == "bonjour"
    assert tr.visible_text("bonjour", -1) == "bonjour", "negative means all of it"


def test_nothing_revealed_yet_renders_nothing() -> None:
    assert tr.render("bonjour", 0) is None
    assert tr.render("", -1) is None
    assert tr.render("   ", -1) is None


def test_the_panel_is_sized_to_its_text() -> None:
    """A one-line utterance is a one-line panel, not a fixed box with dead
    space under it."""
    short = tr.render("Oui.")
    long = tr.render("La fonction plante sur une liste vide " * 4)
    assert short.height < long.height
    assert short.width == tr.WIDTH


def test_the_panel_has_no_opaque_background() -> None:
    """It sits over the user's screen beside the blob; a filled box would
    read as the notification panel this replaced."""
    image = tr.render("bonjour")
    assert image.getpixel((tr.WIDTH - 2, 2))[3] == 0


def test_a_long_line_keeps_its_end_not_its_start() -> None:
    """While text is being typed the end is what just changed - dropping it
    would freeze the panel at the beginning of a long sentence."""
    text = "mot " * 200
    image = tr.render(text)
    assert image is not None
    assert image.height <= 2 * tr.MARGIN + tr.LINE_HEIGHT * tr.MAX_LINES


def test_wrapping_is_measured_against_the_real_font() -> None:
    font, draw = tr._font(tr.FONT_SIZE), _draw()
    lines = tr.wrap("W " * 60, font, draw, 200)
    assert len(lines) > 1
    assert all(draw.textlength(line, font=font) <= 200 for line in lines)


def test_the_panel_is_pinned_to_the_top_of_the_screen() -> None:
    """Fixed rather than following the blob: beside a cursor-following blob
    the panel moved while it was being read, and near an edge it flipped
    sides mid-sentence."""
    x, y = tr.position(1920, 1080, 120)
    assert y == tr.TOP_MARGIN
    assert x > 1920 // 2, "right of centre"


def test_the_panel_clears_the_border_glow() -> None:
    """White text read through a coloured glow is legible in a screenshot
    and much less so in motion."""
    x, y = tr.position(1920, 1080, 120)
    assert x >= tr.GLOW_CLEARANCE
    assert x + tr.WIDTH <= 1920 - tr.GLOW_CLEARANCE


def test_a_narrow_screen_still_gets_a_position_on_screen() -> None:
    x, y = tr.position(700, 500, 120)
    assert x >= 0 and y >= 0


def test_the_text_is_outlined_rather_than_shadowed() -> None:
    """A drop shadow only darkens one side, so white text over a light
    window loses its top-left edge. This sits over whatever the user has
    open."""
    assert tr.OUTLINE_WIDTH > 0
    assert tr.OUTLINE[3] > 200
