"""The pixel-art pointer - see `heypeer/tray/cursor_render.py`.

Asserted on the images and paths the module returns, since it owns no
window: that is what makes it checkable in a sandbox with no display.
"""

import pytest

from heypeer.tray import cursor_render as cursor


@pytest.fixture(autouse=True)
def _default_color():
    """Colour is module state, so a test that changes it must not leak."""
    cursor.set_color(cursor.DEFAULT_COLOR)
    yield
    cursor.set_color(cursor.DEFAULT_COLOR)


def test_the_default_is_the_red_the_user_asked_for() -> None:
    assert cursor.DEFAULT_COLOR == (255, 0, 0)
    assert cursor.color() == (255, 0, 0)


def test_the_colour_is_customisable_for_onboarding() -> None:
    cursor.set_color((0, 200, 120))
    assert cursor.color() == (0, 200, 120)


def test_an_out_of_range_colour_is_clamped_not_rejected() -> None:
    """Onboarding hands this whatever a colour picker produced."""
    cursor.set_color((300, -20, 40))
    assert cursor.color() == (255, 0, 40)


def test_the_chosen_colour_actually_reaches_the_pixels() -> None:
    """A setting that renders identically either way is not a setting."""
    red = cursor.render().tobytes()
    cursor.set_color((0, 128, 255))
    assert cursor.render().tobytes() != red


def test_the_pointer_renders_with_transparent_edges() -> None:
    """It is composited over whatever is on screen; an opaque square would
    black out the control underneath it."""
    image = cursor.render()
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0


def test_the_tip_sits_at_the_centre_of_the_surface() -> None:
    """Callers position by the click coordinate, which is the tip."""
    image = cursor.render()
    origin = (cursor.SURFACE // 2) * cursor.PIXEL_SCALE
    assert image.getpixel((origin + 1, origin + 1))[3] > 0


def test_pixels_stay_square() -> None:
    """The whole art direction. A block's interior must be one flat colour -
    any resampling would produce a gradient across it instead."""
    image = cursor.render()
    origin = (cursor.SURFACE // 2) * cursor.PIXEL_SCALE
    # Inside the arrow body, a few rows down from the tip.
    x = origin + 2 * cursor.PIXEL_SCALE
    y = origin + 6 * cursor.PIXEL_SCALE
    block = {image.getpixel((x + dx, y + dy)) for dx in range(cursor.PIXEL_SCALE)
             for dy in range(cursor.PIXEL_SCALE)}
    assert len(block) == 1, "a block is not one flat colour - it got resampled"


def test_the_press_burst_changes_the_frame() -> None:
    assert cursor.render(press=0.0).tobytes() != cursor.render(press=0.5).tobytes()


def test_press_is_clamped_rather_than_drawn_out_of_bounds() -> None:
    assert cursor.render(press=5.0).size == cursor.render().size
    assert cursor.render(press=-3.0).size == cursor.render().size


def test_a_trail_is_drawn_behind_the_pointer() -> None:
    plain = cursor.render().tobytes()
    trailed = cursor.render(trail=[(-30, -15), (-20, -10), (-10, -5)]).tobytes()
    assert plain != trailed


# --- movement ---

def test_the_path_starts_and_ends_exactly_where_asked() -> None:
    """However large the arc bulges, it must land on the target - this is a
    click coordinate, not a decoration."""
    path = cursor.travel_path((100, 100), (800, 400), 30)
    assert path[0] == (100, 100)
    assert path[-1] == (800, 400)


def test_the_path_is_curved_not_straight() -> None:
    """A straight linear slide reads as a UI animation rather than as
    something arriving."""
    start, end = (0, 0), (400, 0)
    path = cursor.travel_path(start, end, 21)
    midpoint = path[len(path) // 2]
    assert abs(midpoint[1]) > 5, "the arc has no bulge"


def test_the_pointer_decelerates_onto_its_target() -> None:
    """Slowing into the target is what makes it look like aiming."""
    path = cursor.travel_path((0, 0), (600, 0), 30)
    first_hop = abs(path[1][0] - path[0][0])
    last_hop = abs(path[-1][0] - path[-2][0])
    middle_hop = abs(path[15][0] - path[14][0])
    assert middle_hop > first_hop and middle_hop > last_hop


def test_a_zero_length_move_does_not_divide_by_zero() -> None:
    assert cursor.travel_path((50, 50), (50, 50), 10) == [(50, 50)] * 10


def test_a_single_step_path_is_just_the_destination() -> None:
    assert cursor.travel_path((0, 0), (10, 10), 1) == [(10, 10)]


def test_trail_offsets_are_relative_to_the_current_point() -> None:
    """The pointer's window moves with it, so the trail must be drawn
    inside a surface centred on the tip."""
    path = [(0, 0), (10, 0), (20, 0), (30, 0)]
    offsets = cursor.trail_offsets(path, 3, length=3)
    assert offsets == [(-30, 0), (-20, 0), (-10, 0)]


def test_far_trail_points_are_dropped_not_clamped() -> None:
    """A clamped point piles up on the edge and reads as a smear stuck to
    the cursor."""
    path = [(0, 0), (5000, 0), (10, 0)]
    offsets = cursor.trail_offsets(path, 2, length=3)
    assert all(abs(dx) < cursor.SURFACE * cursor.PIXEL_SCALE for dx, _ in offsets)


def test_the_first_point_of_a_path_has_no_trail() -> None:
    path = cursor.travel_path((0, 0), (100, 100), 10)
    assert cursor.trail_offsets(path, 0) == []
