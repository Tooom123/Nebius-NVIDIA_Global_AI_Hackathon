"""The countdown pill - see `heypeer/tray/countdown_render.py`.

Asserted on the image the renderer returns, since it owns no window: that
is exactly what makes it checkable in a sandbox with no display.
"""

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


def test_the_dial_travels_the_palette_as_it_drains() -> None:
    """Four steps rather than one flat colour then a jump: the dial now
    moves through Apple Intelligence's palette as time runs out, which is
    what stops it reading as a generic progress bar."""
    from heypeer.tray.countdown_render import CALM, MID

    assert arc_color(1.0) == CALM
    assert arc_color(0.4) == MID
    assert arc_color(0.15) == WARNING
    assert arc_color(0.05) == URGENT
    assert len({arc_color(f) for f in (1.0, 0.4, 0.15, 0.05)}) == 4


def test_the_countdown_uses_the_same_palette_as_the_blob() -> None:
    """Two of Hey Peer's own surfaces in unrelated colours read as two
    applications."""
    from heypeer.tray import blob_render, countdown_render

    apple = {blob_render.APPLE_BLUE, blob_render.APPLE_PURPLE,
             blob_render.APPLE_PINK, blob_render.APPLE_ORANGE}
    assert {arc_color(f) for f in (1.0, 0.4, 0.15, 0.05)} <= apple


def test_a_ringing_timer_shows_a_stop_button_instead_of_the_dial() -> None:
    """The alarm replaces the countdown in the same place - the user was
    already watching this pill, so that is where they look when it fires."""
    from heypeer.tray.countdown_render import render as draw

    running = draw("0:05", "les pâtes", 0.05).tobytes()
    ringing = draw("0:00", "les pâtes", 0.0, ringing=True).tobytes()
    assert running != ringing


def test_the_stop_button_hit_area_matches_where_it_is_drawn() -> None:
    """Drawing and hit-testing must come from one number, or the button
    moves without its clickable area following."""
    from heypeer.tray.countdown_render import HEIGHT, WIDTH, stop_button_rect

    left, top, right, bottom = stop_button_rect()
    assert 0 < left < right < WIDTH
    assert 0 < top < bottom < HEIGHT
    assert abs((top + bottom) // 2 - HEIGHT // 2) <= 1, "vertically centred"


def test_a_ringing_timer_renders_with_and_without_a_label() -> None:
    from heypeer.tray.countdown_render import render as draw

    assert draw("0:00", "les pâtes", 0.0, ringing=True).size == (WIDTH, HEIGHT)
    assert draw("0:00", "", 0.0, ringing=True).size == (WIDTH, HEIGHT)


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
