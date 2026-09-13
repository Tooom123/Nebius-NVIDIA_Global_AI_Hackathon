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
    """Four-on-the-floor kick and a backbeat snare: the point of a demo
    pattern is that the audience understands it in three seconds."""
    assert flstudio.PATTERN[flstudio.ROW_KICK] == (0, 4, 8, 12)
    assert flstudio.PATTERN[flstudio.ROW_SNARE] == (4, 12)


def test_clicks_are_ordered_row_by_row() -> None:
    """The pointer travels along each instrument's line rather than
    zig-zagging down the grid - laying down a part, not scattering dots."""
    clicks = flstudio.pattern_clicks(WINDOW)
    kick_count = len(flstudio.PATTERN[flstudio.ROW_KICK])
    kick_rows = {y for _, y in clicks[:kick_count]}
    assert len(kick_rows) == 1, "the kick's clicks share one row"


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
