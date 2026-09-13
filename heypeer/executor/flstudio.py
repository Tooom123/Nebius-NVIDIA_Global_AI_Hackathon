"""Laying a drum pattern into FL Studio's step sequencer, by clicking it.

## What this is, and what it is not

A scripted demo path, and deliberately labelled as one. It opens FL Studio
and clicks a fixed set of steps in the sequencer grid. It does not read the
project, does not know what is already in it, and does not decide what
would suit the track - so nothing here claims to.

That honesty matters in the spoken line too: Hey Peer says it is adding a
drum pattern, never that it analysed anything. A demo that overstates what
it did is the one thing a judge will remember afterwards.

## Why coordinates, when every other click goes through UI Automation

`executor/ui_elements.py` finds controls by name in the accessibility tree,
which is exact and survives a window moving. FL Studio exposes almost none
of itself that way: it draws its own interface, so the tree has a window
and little else. The choice is between clicking coordinates and not
clicking at all.

So this is the fragile path, and it is fragile in a specific, testable way:
the grid's position depends on the window being maximised at a known
resolution. `GRID` below is expressed as *fractions of the window*, not
pixels, so a different screen scales rather than misses entirely - but a
different FL Studio layout, a collapsed browser panel or a moved sequencer
will put the clicks somewhere wrong.

## The pattern

A four-on-the-floor kick, backbeat snare, eighth-note hats: the most
recognisable drum pattern there is, which is the right choice for a demo
where the audience has three seconds to understand what happened. Written
as steps-per-row rather than as coordinates so it reads as music.
"""

import time

# Rows in the channel rack, top to bottom, as they exist in the user's own
# project - read off a screenshot of it rather than assumed from a stock
# template, which is what the first version got wrong.
#
# Their project has two channels, not four: a sample and FL Keys. So the
# pattern is laid into those two rows rather than into kick/clap/hat/snare
# that are not there. Naming them by position is the honest description -
# what they *contain* is the user's business, and the demo is muted anyway.
ROW_FIRST = 0
ROW_SECOND = 1

# Which of the 16 steps to switch on, per row.
#
# Chosen to look right rather than to sound right, which is the honest way
# round here: the demo is muted and music is added in post, so what the
# audience judges is the *shape* of the grid. A four-on-the-floor kick with
# a ghost note, a backbeat snare with a pickup, sixteenth hats and claps on
# the offbeats fills the grid the way a real pattern does - where the
# minimal version left most of it empty and read as a placeholder.
#
# It is also a pattern a producer would not wince at: the ghost kick before
# the three and the snare pickup into the four are what an actual person
# would put there, rather than a metronome.
PATTERN = {
    ROW_FIRST: (0, 4, 7, 8, 12),
    ROW_SECOND: (2, 6, 10, 14),
}

# The step grid's position, as fractions of the window rather than pixels,
# so a different resolution scales instead of missing. Measured from FL
# Studio's default channel rack layout.
# Measured off a real screenshot of the user's FL Studio at 1920x1080, not
# estimated. The first version was guessed and every number was wrong -
# step_dx especially, at 0.0246 against the real 0.0083, so the clicks
# walked three times too far right and left the grid entirely after a few
# steps. That is what put them in the playlist, where a left click paints
# with the selected pattern - hence the copies of the user's first clip.
#
# Still fractions of the window rather than pixels, so another resolution
# scales. What this cannot survive is a different FL Studio layout: these
# numbers describe the channel rack docked top-left at its default size.
GRID = {
    "left": 0.2250,     # centre of step 1
    "top": 0.1343,      # centre of row 1
    "step_dx": 0.0083,  # horizontal spacing between steps
    "row_dy": 0.0278,   # vertical spacing between rows
}

# Between clicks. Fast enough to look deliberate rather than laboured,
# slow enough that FL Studio registers each one - a burst of clicks faster
# than its own UI loop drops some, which shows up as a pattern with holes.
CLICK_INTERVAL = 0.055

# A beat before the first click. The user asked for Hey Peer to "think for
# a second" and then have the pattern appear: without it the clicks start
# while it is still speaking, which reads as a macro firing rather than as
# an assistant deciding something.
THINKING_SECONDS = 1.2

# How long to wait for FL Studio to come up before clicking into it.
# Generous: it loads plugins on startup, and clicking into a window that is
# still initialising does nothing at best.
LAUNCH_WAIT_SECONDS = 6.0


def step_position(
    step: int, row: int, window: "tuple[int, int, int, int]"
) -> "tuple[int, int]":
    """Screen pixels for one step button, given the FL Studio window as
    `(left, top, width, height)`.

    Pure, so the arithmetic can be checked without FL Studio - which is the
    only part of this module that can be tested at all.
    """
    left, top, width, height = window
    x = left + width * (GRID["left"] + step * GRID["step_dx"])
    y = top + height * (GRID["top"] + row * GRID["row_dy"])
    return (round(x), round(y))


def pattern_clicks(window: "tuple[int, int, int, int]") -> "list[tuple[int, int]]":
    """Every click the pattern needs, in the order to make them.

    Ordered row by row rather than step by step: the pointer travels along
    each instrument's line instead of zig-zagging down the grid, which reads
    as laying down a part rather than as scattering dots.
    """
    clicks = []
    for row in (ROW_FIRST, ROW_SECOND):
        for step in PATTERN[row]:
            clicks.append(step_position(step, row, window))
    return clicks


def focus_window() -> bool:
    """Brings FL Studio to the front, and returns whether it worked.

    Clicking into a window that is not focused is not reliable: the first
    click is frequently consumed activating the window rather than pressing
    what is under the pointer, and on a second monitor the foreground window
    is usually somewhere else entirely. Both of those look exactly like the
    click going to the wrong place, which is what the user saw.
    """
    try:
        import uiautomation as auto

        window = auto.WindowControl(searchDepth=1, SubName="FL Studio")
        if not window.Exists(maxSearchSeconds=1):
            return False
        window.SetActive()
        # A beat for the activation to actually take effect - SetActive
        # returns before Windows has finished raising the window, and
        # clicking into the gap is the very problem this avoids.
        time.sleep(0.35)
        return True
    except Exception:
        return False


def find_window() -> "tuple[int, int, int, int] | None":
    """FL Studio's window rectangle, or None if it is not open.

    Matched on the title containing "FL Studio", which is how the
    application names every one of its windows regardless of the project.
    """
    try:
        import uiautomation as auto

        window = auto.WindowControl(searchDepth=1, SubName="FL Studio")
        if not window.Exists(maxSearchSeconds=1):
            return None
        rect = window.BoundingRectangle
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        return None


def launch() -> bool:
    """Starts FL Studio if it is not already running, and returns whether a
    window is there to click into afterwards."""
    if find_window() is not None:
        return True
    try:
        from heypeer.executor import apps

        app = apps.resolve_app("fl studio")
        if app is None:
            return False
        apps.launch(app)
    except Exception:
        return False

    deadline = time.time() + LAUNCH_WAIT_SECONDS
    while time.time() < deadline:
        if find_window() is not None:
            return True
        time.sleep(0.4)
    return False


def diagnose() -> str:
    """A report of what this module currently sees, for when the clicks land
    somewhere wrong.

    Printed rather than logged because it is run by hand, on the machine
    that has the problem:

        python -c "from heypeer.executor import flstudio; print(flstudio.diagnose())"

    Multi-monitor coordinate bugs are almost impossible to reason about from
    a description - "the click went to the other screen" has several
    distinct causes - and this separates them: whether the window rectangle
    is right, whether the virtual desktop spans both screens, and where the
    first click would actually land.
    """
    lines = []

    window = find_window()
    lines.append(f"FL Studio window: {window}")
    if window is None:
        lines.append("  -> not open, or uiautomation is not installed.")
        return "\n".join(lines)

    try:
        from heypeer.executor import cursor_control

        screen = cursor_control.virtual_screen()
        lines.append(f"Virtual desktop:  {screen}  (left, top, width, height)")
        if window[0] < screen[0] or window[0] + window[2] > screen[0] + screen[2]:
            lines.append("  -> the window is OUTSIDE the reported desktop:")
            lines.append("     the process is probably not DPI-aware.")

        first = pattern_clicks(window)[0]
        lines.append(f"First click:      {first}")
        lines.append(f"Absolute coords:  {cursor_control.to_absolute(*first, screen)}")
        lines.append(f"Cursor now at:    {cursor_control.cursor_position()}")
    except Exception as exc:
        lines.append(f"  -> could not read screen metrics: {exc}")

    lines.append(f"Steps to click:   {len(pattern_clicks(window))}")
    return "\n".join(lines)
