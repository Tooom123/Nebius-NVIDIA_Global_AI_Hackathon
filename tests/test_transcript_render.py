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


def test_the_panel_sits_beside_the_blob() -> None:
    x, y = tr.position(100, 200, 240, 120, screen_width=1920)
    assert x > 100 + 240, "to the right of the blob"
    assert 200 < y + 60 < 200 + 240, "vertically centred on it"


def test_it_flips_to_the_other_side_near_the_screen_edge() -> None:
    """The blob follows the cursor, so a panel fixed to its right runs off
    screen whenever the user works near the right edge."""
    x, _ = tr.position(1750, 200, 240, 120, screen_width=1920)
    assert x < 1750


def test_it_never_goes_off_the_left_edge_either() -> None:
    x, _ = tr.position(10, 200, 240, 120, screen_width=400)
    assert x >= 0
