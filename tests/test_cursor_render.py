"""The flying cursor - see `heypeer/tray/cursor_render.py`.

Asserted on the frames and geometry the module returns, since it owns no
window.
"""

import math

import pytest

from heypeer.tray import cursor_render as cursor


@pytest.fixture(autouse=True)
def _default_color():
    """Colour is module state, so a test that changes it must not leak."""
    cursor.set_color(cursor.DEFAULT_COLOR)
    yield
    cursor.set_color(cursor.DEFAULT_COLOR)


# --- colour ---

def test_the_default_stays_the_red_the_user_chose() -> None:
    assert cursor.DEFAULT_COLOR == (255, 0, 0)


def test_the_chosen_colour_actually_reaches_the_pixels() -> None:
    """A setting that renders identically either way is not a setting - and
    frames are cached, so changing colour must invalidate them."""
    red = cursor.render().tobytes()
    cursor.set_color((0, 128, 255))
    assert cursor.render().tobytes() != red


def test_an_out_of_range_colour_is_clamped() -> None:
    cursor.set_color((300, -20, 40))
    assert cursor.color() == (255, 0, 40)


# --- the frame ---

def test_the_frame_has_transparent_corners() -> None:
    """Composited over whatever is on screen."""
    image = cursor.render()
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0


def test_the_tip_sits_on_the_centre_of_the_surface() -> None:
    """This cursor clicks, so the visible point must be on the target
    coordinate - Clicky centres its triangle because it only points."""
    image = cursor.render()
    c = cursor.SURFACE // 2
    assert image.getpixel((c, c))[3] > 100


def test_edges_are_antialiased_not_hard() -> None:
    """The pixel-art version wanted hard edges; this one is the reverse.
    An edge with no partial alpha would look like a rendering bug."""
    alphas = {px[3] for px in cursor.render().getdata()}
    assert any(20 < a < 235 for a in alphas)


def test_the_glow_extends_past_the_triangle() -> None:
    """A halo in its own colour, not a hard shape on the screen."""
    image = cursor.render()
    c = cursor.SURFACE // 2
    # Directly behind the tip, opposite the heading, is outside the
    # triangle at rest but within the glow.
    assert image.getpixel((c - 4, c - 4))[3] > 0


def test_a_turned_cursor_draws_differently() -> None:
    assert cursor.render(angle=-35).tobytes() != cursor.render(angle=90).tobytes()


def test_the_press_ring_changes_the_frame() -> None:
    assert cursor.render(press=0.0).tobytes() != cursor.render(press=0.5).tobytes()


def test_out_of_range_inputs_are_clamped_not_drawn_outside() -> None:
    assert cursor.render(scale=9, glow=9, press=9).size == (cursor.SURFACE, cursor.SURFACE)


def test_the_triangle_fits_the_surface_at_full_flight_scale() -> None:
    """Pointing any direction from the centre at 1.3x, it must not clip."""
    for angle in range(0, 360, 15):
        for x, y in cursor.triangle_points(
            cursor.SURFACE / 2, cursor.SURFACE / 2, angle,
            cursor.TRIANGLE_SIZE * (1 + cursor.FLIGHT_SCALE_PEAK),
        ):
            assert 0 <= x <= cursor.SURFACE and 0 <= y <= cursor.SURFACE


def test_the_tip_is_the_first_corner_and_leads_the_heading() -> None:
    tip, b1, b2 = cursor.triangle_points(0, 0, 90, 10)  # heading right
    assert tip == (0, 0)
    assert b1[0] < 0 and b2[0] < 0, "the base trails behind a rightward heading"


# --- the flight ---

def test_the_flight_lands_exactly_on_the_target() -> None:
    """However the arc bows, this is a click coordinate."""
    frames = cursor.flight_frames((100, 900), (1500, 200))
    assert frames[-1][:2] == (1500, 200)


def test_the_flight_arcs_upward() -> None:
    """Clicky's arc bows up, not sideways - a parabola, not a swerve."""
    frames = cursor.flight_frames((0, 500), (800, 500))
    middle = frames[len(frames) // 2]
    assert middle[1] < 500 - 20


def test_the_cursor_turns_to_face_its_direction_of_travel() -> None:
    """The detail that makes it read as travelling rather than dragged."""
    rightward = cursor.flight_frames((0, 500), (800, 500))
    leftward = cursor.flight_frames((800, 500), (0, 500))
    mid_r = rightward[len(rightward) // 2][2] % 360
    mid_l = leftward[len(leftward) // 2][2] % 360
    assert abs(mid_r - 90) < 15, "tip facing right while moving right"
    assert abs(mid_l - 270) < 15, "tip facing left while moving left"


def test_it_swells_at_the_top_of_the_arc_and_settles_on_landing() -> None:
    frames = cursor.flight_frames((0, 0), (1000, 0))
    peak = max(f[3] for f in frames)
    assert 1.25 < peak <= 1.31
    assert frames[-1][3] == 1.0


def test_a_short_hop_is_quick_and_a_long_flight_is_capped() -> None:
    assert cursor.flight_seconds((0, 0), (50, 0)) == cursor.FLIGHT_MIN_SECONDS
    assert cursor.flight_seconds((0, 0), (5000, 0)) == cursor.FLIGHT_MAX_SECONDS
    assert cursor.flight_seconds((0, 0), (800, 0)) == pytest.approx(1.0)


def test_it_decelerates_onto_the_target() -> None:
    """Slowing into the target is what makes it look like aiming."""
    frames = cursor.flight_frames((0, 0), (1000, 0))
    xs = [f[0] for f in frames]
    middle = abs(xs[len(xs) // 2] - xs[len(xs) // 2 - 1])
    last = abs(xs[-1] - xs[-2])
    assert middle > last * 3


def test_a_zero_length_flight_does_not_divide_by_zero() -> None:
    frames = cursor.flight_frames((40, 40), (40, 40))
    assert frames and all(f[:2] == (40, 40) for f in frames)
