"""The countdown pill - see `heypeer/tray/countdown_render.py`.

Asserted on the image the renderer returns, since it owns no window: that
is exactly what makes it checkable in a sandbox with no display.
"""

from heypeer.tray.blob_render import PALETTE_CYAN
from heypeer.tray.countdown_render import (
    HEIGHT,
    URGENT,
    WARNING,
    WIDTH,
    arc_color,
    position,
    render,
    _elide,
)


def test_render_returns_a_correctly_sized_rgba_frame() -> None:
    image = render("4:37", "les pâtes", 0.5)
    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "RGBA"


def test_the_pill_has_transparent_corners() -> None:
    """It is composited straight onto the desktop - a rounded pill inside an
    opaque rectangle would show as a black box."""
    image = render("4:37", "", 0.5)
    assert image.getpixel((0, 0))[3] == 0


def test_the_pill_is_opaque_in_the_middle() -> None:
    image = render("4:37", "", 0.5)
    assert image.getpixel((WIDTH // 2, HEIGHT // 2))[3] > 200


def test_the_dial_warns_then_turns_urgent_as_time_runs_out() -> None:
    assert arc_color(1.0) == PALETTE_CYAN
    assert arc_color(0.5) == PALETTE_CYAN
    assert arc_color(0.15) == WARNING
    assert arc_color(0.05) == URGENT


def test_a_finished_timer_still_renders() -> None:
    """A reminder that has just fired, or one created with no duration,
    must not blow up the renderer."""
    assert render("0:00", "x", 0.0).size == (WIDTH, HEIGHT)


def test_an_out_of_range_fraction_is_clamped_rather_than_drawn_wrong() -> None:
    assert render("9:99", "", 5.0).size == (WIDTH, HEIGHT)
    assert render("0:00", "", -2.0).size == (WIDTH, HEIGHT)


def test_labelled_and_unlabelled_frames_both_render() -> None:
    assert render("1:00", "", 0.5).size == (WIDTH, HEIGHT)
    assert render("1:00", "les pâtes", 0.5).size == (WIDTH, HEIGHT)


def test_a_long_label_is_elided_not_wrapped() -> None:
    assert _elide("les pâtes pour ce soir avec les invités", 18).endswith("…")
    assert len(_elide("les pâtes pour ce soir avec les invités", 18)) == 18


def test_a_short_label_is_left_alone() -> None:
    assert _elide("les pâtes", 18) == "les pâtes"


def test_position_sits_inside_the_top_right_of_the_screen() -> None:
    x, y = position(1920, 1080)
    assert 0 < x < 1920 - WIDTH + 1
    assert 0 < y < 1080 - HEIGHT
