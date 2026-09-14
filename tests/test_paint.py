"""The Paint tribute drawing - see `heypeer/executor/paint.py`."""

from heypeer.executor import paint


CANVAS = (0, 0, 1000, 600)


def test_every_letter_of_the_phrase_has_a_glyph() -> None:
    """A missing glyph is silently skipped, so the phrase would draw with a
    hole in it and nothing would say why."""
    for char in paint.PHRASE:
        assert char in paint.GLYPHS, char


def test_the_phrase_is_the_tribute() -> None:
    assert "".join(paint.PHRASE) == "I <3 NVIDIA & NEBIUS"


def test_strokes_stay_inside_the_canvas() -> None:
    """A stroke starting above the canvas lands on Paint's ribbon and
    clicks a tool instead of drawing."""
    left, top, width, height = CANVAS
    for stroke in paint.layout(CANVAS):
        for x, y in stroke:
            assert left <= x <= left + width
            assert top <= y <= top + height


def test_the_phrase_is_centred() -> None:
    strokes = paint.layout(CANVAS)
    xs = [x for stroke in strokes for x, _ in stroke]
    left_gap = min(xs) - CANVAS[0]
    right_gap = (CANVAS[0] + CANVAS[2]) - max(xs)
    assert abs(left_gap - right_gap) < 40


def test_it_scales_to_the_canvas_it_is_given() -> None:
    small = paint.layout((0, 0, 500, 300))
    large = paint.layout((0, 0, 1000, 600))
    small_width = max(x for s in small for x, _ in s) - min(x for s in small for x, _ in s)
    large_width = max(x for s in large for x, _ in s) - min(x for s in large for x, _ in s)
    assert large_width > small_width * 1.5


def test_a_narrow_canvas_does_not_overflow() -> None:
    """Sized to whichever bound binds first - a long phrase on a wide
    canvas is limited by height, on a narrow one by width."""
    canvas = (0, 0, 400, 800)
    for stroke in paint.layout(canvas):
        for x, _ in stroke:
            assert 0 <= x <= 400


def test_each_stroke_is_a_continuous_pen_down() -> None:
    """Glyphs are lists of strokes rather than one path: I is three
    separate pen-downs, and joining them would draw the pen travelling."""
    assert len(paint.GLYPHS["I"]["strokes"]) == 3
    assert len(paint.GLYPHS["<3"]["strokes"]) == 1, "the heart is one stroke"


def test_every_stroke_has_at_least_two_points() -> None:
    """A one-point stroke is a click, not a line - it would press whatever
    is under it."""
    for stroke in paint.layout(CANVAS):
        assert len(stroke) >= 2


def test_the_canvas_area_avoids_the_ribbon() -> None:
    """Paint's ribbon is at the top and its status bar at the bottom."""
    window = (0, 0, 1920, 1080)
    left, top, width, height = paint.canvas_area(window)
    assert top > 1080 * 0.25, "clear of the ribbon"
    assert top + height < 1080 * 0.95, "clear of the status bar"


def test_a_space_draws_nothing_but_advances() -> None:
    assert paint.GLYPHS[" "]["strokes"] == []
    assert paint.GLYPHS[" "]["width"] > 0


def test_the_whole_latin_alphabet_can_be_drawn() -> None:
    """A half-alphabet fails silently at the worst moment. Found by asking
    Nemotron for three phrases and watching one fail on the J of JURY."""
    import string

    assert all(letter in paint.GLYPHS for letter in string.ascii_uppercase)


def test_a_phrase_is_uppercased_and_the_heart_kept_whole() -> None:
    """The heart is two characters in text and one glyph on the canvas -
    splitting it would try to draw "<" and "3", neither of which exists."""
    assert paint.parse_phrase("i <3 nvidia")[:3] == ["I", " ", "<3"]


def test_drawable_rejects_what_has_no_glyph() -> None:
    """Checked before drawing rather than skipping mid-stroke: a phrase
    missing letters is not a shorter phrase, it is unreadable."""
    assert paint.drawable(paint.parse_phrase("MERCI JURY")) is True
    assert paint.drawable(paint.parse_phrase("merci 2026")) is False, "digits"
    assert paint.drawable(paint.parse_phrase("ça va")) is False, "accents"


def test_a_chosen_phrase_lays_out_like_the_default() -> None:
    strokes = paint.layout(CANVAS, paint.parse_phrase("MERCI"))
    assert strokes
    for stroke in strokes:
        for x, y in stroke:
            assert CANVAS[0] <= x <= CANVAS[0] + CANVAS[2]
            assert CANVAS[1] <= y <= CANVAS[1] + CANVAS[3]
