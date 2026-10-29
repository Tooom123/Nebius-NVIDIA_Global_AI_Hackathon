"""The scripted FL Studio demo path - see `heypeer/executor/flstudio.py`.

Only the arithmetic is testable here: there is no FL Studio, and the whole
approach rests on assumptions about its window that can only be checked by
running it. What these do cover is that the grid maths is right and scales,
which is the part that would silently click the wrong cells.
"""

from heypeer.executor import flstudio


WINDOW = (0, 0, 1920, 1080)


def test_steps_advance_horizontally_and_rows_vertically() -> None:
    first = flstudio.step_position(0, 0, WINDOW)
    next_step = flstudio.step_position(1, 0, WINDOW)
    next_row = flstudio.step_position(0, 1, WINDOW)

    assert next_step[0] > first[0] and next_step[1] == first[1]
    assert next_row[1] > first[1] and next_row[0] == first[0]


def test_the_grid_scales_with_the_window() -> None:
    """Expressed as fractions rather than pixels, so a different resolution
    scales instead of missing the grid entirely."""
    small = flstudio.step_position(4, 1, (0, 0, 1280, 720))
    large = flstudio.step_position(4, 1, (0, 0, 2560, 1440))
    # Within a pixel: the position is rounded to whole pixels, so doubling
    # the window doubles the coordinate give or take the rounding.
    assert abs(large[0] - small[0] * 2) <= 1
    assert abs(large[1] - small[1] * 2) <= 1


def test_a_window_that_is_not_at_the_origin_is_offset() -> None:
    """FL Studio on a second monitor, or simply not maximised."""
    at_origin = flstudio.step_position(2, 1, (0, 0, 1920, 1080))
    moved = flstudio.step_position(2, 1, (100, 50, 1920, 1080))
    assert moved == (at_origin[0] + 100, at_origin[1] + 50)


def test_every_click_lands_inside_the_window() -> None:
    """A coordinate outside the window would click whatever is behind it."""
    for x, y in flstudio.pattern_clicks(WINDOW):
        assert 0 < x < 1920
        assert 0 < y < 1080


def test_the_pattern_is_a_recognisable_beat() -> None:
    """Downbeats on the first row, offbeats on the second - that is what
    makes the grid read as a beat rather than as scattered dots."""
    first = flstudio.PATTERN[flstudio.ROW_FIRST]
    second = flstudio.PATTERN[flstudio.ROW_SECOND]
    assert {0, 4, 8, 12} <= set(first), "downbeats"
    assert set(second) & {2, 6, 10, 14}, "offbeats against them"


def test_every_row_has_something_in_it() -> None:
    """An empty row is a channel that looks forgotten."""
    assert all(steps for steps in flstudio.PATTERN.values())


def test_no_step_falls_outside_the_sixteen() -> None:
    """A 17th step is not a wider pattern, it is a click on whatever is
    beside the grid."""
    for steps in flstudio.PATTERN.values():
        assert all(0 <= step <= 15 for step in steps)


def test_the_grid_matches_the_measured_screenshot() -> None:
    """Regression guard on the numbers themselves. The first version was
    estimated and every one was wrong - step_dx was 0.0246 against the real
    0.0083, so clicks walked three times too far right and left the grid
    entirely, landing in the playlist where a left click paints with the
    selected pattern. That is what produced copies of the user's first clip
    instead of drums.

    Checked as window-local pixels at 1920x1080, which is what was measured
    off the screenshot and what a future edit can be compared against.
    """
    window = (0, 0, 1920, 1080)
    first = flstudio.step_position(0, 0, window)
    sixteenth = flstudio.step_position(15, 0, window)
    second_row = flstudio.step_position(0, 1, window)

    assert 425 <= first[0] <= 440, "step 1 sits at the left of the grid"
    assert 138 <= first[1] <= 152, "row 1 is near the top of the rack"
    assert 660 <= sixteenth[0] <= 685, "step 16 is still inside the grid"
    assert 165 <= second_row[1] <= 180, "row 2 is one row down, not a panel away"


def test_clicks_are_ordered_row_by_row() -> None:
    """The pointer travels along each instrument's line rather than
    zig-zagging down the grid - laying down a part, not scattering dots."""
    clicks = flstudio.pattern_clicks(WINDOW)
    first_count = len(flstudio.PATTERN[flstudio.ROW_FIRST])
    first_rows = {y for _, y in clicks[:first_count]}
    assert len(first_rows) == 1, "the first row's clicks share one y"


def test_the_click_count_matches_the_pattern() -> None:
    expected = sum(len(steps) for steps in flstudio.PATTERN.values())
    assert len(flstudio.pattern_clicks(WINDOW)) == expected


def test_no_window_is_reported_rather_than_raising(monkeypatch) -> None:
    """uiautomation absent, FL Studio closed - the caller says the same
    thing either way."""
    import sys

    monkeypatch.setitem(sys.modules, "uiautomation", None)
    assert flstudio.find_window() is None


def test_diagnose_reports_rather_than_raising_when_nothing_is_open(monkeypatch) -> None:
    """It is run by hand on a machine that already has a problem - raising
    would tell the user less than the report does."""
    monkeypatch.setattr(flstudio, "find_window", lambda: None)
    report = flstudio.diagnose()
    assert "not open" in report


def test_diagnose_names_where_the_first_click_would_land(monkeypatch) -> None:
    """"The click went to the other screen" has several distinct causes;
    the report separates them."""
    monkeypatch.setattr(flstudio, "find_window", lambda: (1920, 0, 1920, 1080))
    report = flstudio.diagnose()
    assert "FL Studio window" in report
    assert "(1920, 0, 1920, 1080)" in report
    # The screen-metric lines need ctypes.windll, which only exists on
    # Windows - the report degrades to saying so rather than failing, which
    # is itself the behaviour worth pinning.
    assert "Steps to click" in report


def test_focus_failure_is_reported_rather_than_raised(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "uiautomation", None)
    assert flstudio.focus_window() is False


# --- seeing the step sequencer ---

def _rack_image(rows: int = 3, lit: "set[tuple[int, int]]" = frozenset()):
    """A drawing of a channel rack in FL Studio 21's colours, as measured:
    background 95,104,109, button border 81,87,91, inside 91,97,101, lit
    inside 190,195,198. Buttons 11 px wide at a 16 px pitch, rows 30 px
    apart - and, beside it, a playlist-like grid whose cells touch."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (700, 40 + rows * 30), (95, 104, 109))
    draw = ImageDraw.Draw(image)
    for r in range(rows):
        top = 20 + r * 30
        for step in range(16):
            left = 40 + step * 16
            fill = (190, 195, 198) if (r, step) in lit else (91, 97, 101)
            draw.rectangle((left, top, left + 10, top + 18), fill=fill, outline=(81, 87, 91))
        for cell in range(18):
            left = 400 + cell * 14
            draw.rectangle((left, top, left + 14, top + 18), outline=(60, 64, 66))
    return image


def test_the_rack_is_found_and_the_playlist_is_not() -> None:
    rows = flstudio.find_step_rows(_rack_image(rows=3))
    assert len(rows) == 3
    assert [round(r.y) for r in rows] == [29, 59, 89]
    assert round(rows[0].xs[0]) == 45 and round(rows[0].xs[15]) == 285


def test_rows_are_placed_in_screen_coordinates() -> None:
    """A screenshot of the left screen starts at x = -1920."""
    rows = flstudio.find_step_rows(_rack_image(rows=1), origin=(-1920, 100))
    assert round(rows[0].xs[0]) == -1875 and round(rows[0].y) == 129


def test_lit_steps_are_seen() -> None:
    rows = flstudio.find_step_rows(_rack_image(rows=2, lit={(1, 0), (1, 4)}))
    assert rows[0].lit == (False,) * 16
    assert [i for i, on in enumerate(rows[1].lit) if on] == [0, 4]


def test_the_rows_are_cleared_then_drawn() -> None:
    """A run that found the last run's pattern clicked nothing - the drums
    were never seen being written."""
    rows = flstudio.find_step_rows(_rack_image(rows=3, lit={(1, 0), (1, 3)}))
    moves = flstudio.pattern_moves(rows, {flstudio.ROW_FIRST: [0, 8], flstudio.ROW_SECOND: [0]},
                                   targets=(1, 2))
    assert [(round(x), round(y), b) for x, y, b in moves] == [
        (45, 59, "right"), (45 + 3 * 16, 59, "right"),
        (45, 59, "left"), (45 + 8 * 16, 59, "left"),
        (45, 89, "left"),
    ]


def test_no_moves_when_the_target_rows_are_not_there() -> None:
    rows = flstudio.find_step_rows(_rack_image(rows=2))
    assert flstudio.pattern_moves(rows, None, targets=(7, 8)) == []


def test_the_target_rows_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("HEYPEER_FL_ROWS", "7,8")
    assert flstudio.demo_rows() == (7, 8)
    monkeypatch.setenv("HEYPEER_FL_ROWS", "nonsense")
    assert flstudio.demo_rows() == (flstudio.ROW_FIRST, flstudio.ROW_SECOND)


def _flp(tmp_path, events: bytes):
    path = tmp_path / "song.flp"
    path.write_bytes(b"FLhd" + (6).to_bytes(4, "little") + b"\x00\x00\x10\x00\x60\x00"
                     + b"FLdt" + len(events).to_bytes(4, "little") + events)
    return str(path)


def test_the_tempo_is_read_from_a_modern_project(tmp_path) -> None:
    events = bytes([199, 3]) + b"abc" + bytes([156]) + (128_000).to_bytes(4, "little")
    assert flstudio.tempo_from_project(_flp(tmp_path, events)) == 128


def test_the_tempo_is_read_from_an_old_project(tmp_path) -> None:
    """The user's demo project predates event 156 and has only event 66."""
    events = bytes([9, 1]) + bytes([66]) + (133).to_bytes(2, "little")
    assert flstudio.tempo_from_project(_flp(tmp_path, events)) == 133


def test_not_a_project_has_no_tempo(tmp_path) -> None:
    path = tmp_path / "x.flp"
    path.write_bytes(b"nope")
    assert flstudio.tempo_from_project(str(path)) is None
    assert flstudio.tempo_from_project(None) is None


def test_the_window_size_is_relative_to_the_stage(monkeypatch) -> None:
    monkeypatch.setenv("HEYPEER_STAGE_SCREEN", "-1920,0,1920,1080")
    monkeypatch.setenv("HEYPEER_FL_WINDOW", "0,0,960,1080")
    assert flstudio.window_rect() == (-1920, 0, 960, 1080)


def test_no_window_size_means_maximised(monkeypatch) -> None:
    monkeypatch.delenv("HEYPEER_FL_WINDOW", raising=False)
    assert flstudio.window_rect() is None
