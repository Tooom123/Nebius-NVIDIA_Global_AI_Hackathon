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
from dataclasses import dataclass

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

# Opening a project: FL Studio's own start-up plus the project's plugins
# and samples. Then a moment more once the window exists, for the project
# to finish loading into it.
PROJECT_WAIT_SECONDS = 45.0
PROJECT_SETTLE_SECONDS = 4.0


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


def pattern_clicks(
    window: "tuple[int, int, int, int]", pattern: "dict | None" = None
) -> "list[tuple[int, int]]":
    """Every click the pattern needs, in the order to make them.

    `pattern` is `{row: steps}`, defaulting to `PATTERN`. It is a parameter
    because the pattern is now *composed* by Nemotron from the tempo rather
    than being the constant below - see `NemotronClient.compose_drums`. The
    constant stays as the fallback for when that call fails, since a demo
    that draws nothing is worse than one that draws something ordinary.

    Ordered row by row rather than step by step: the pointer travels along
    each instrument's line instead of zig-zagging down the grid, which reads
    as laying down a part rather than as scattering dots.
    """
    pattern = pattern or PATTERN
    clicks = []
    for row in (ROW_FIRST, ROW_SECOND):
        for step in pattern.get(row, ()):
            clicks.append(step_position(step, row, window))
    return clicks


# --- Seeing the step sequencer ---------------------------------------------
#
# The fractions above describe one layout. A project restores its own -
# where the channel rack floats, how many channels it has - so the demo
# project the user actually brings put every click on the rack's title bar.
# Hence finding the grid in a screenshot instead: the step buttons are a
# shape that is easy to recognise and hard to confuse with anything else.
#
# Measured on FL Studio 21's default skin: each button is about 11 px wide
# with a one-pixel border darker than what surrounds it, sixteen of them at
# a regular pitch with a gap between each. The playlist's grid has the
# pitch but not the gaps - its cells share their borders - which is what
# tells the two apart. A lit step is far brighter than an unlit one (a
# luminance near 190 against 92), so the same picture also says which steps
# are already on.

STEPS = 16
LIT_LUMINANCE = 140


@dataclass(frozen=True)
class StepRow:
    y: float               # screen pixels, centre of the buttons
    xs: "tuple[float, ...]"  # screen pixels, centre of each of the 16 buttons
    lit: "tuple[bool, ...]"


def _luminance(pixel) -> int:
    return (pixel[0] * 299 + pixel[1] * 587 + pixel[2] * 114) // 1000


def find_step_rows(image, origin: "tuple[int, int]" = (0, 0)) -> "list[StepRow]":
    """Every row of step buttons in `image`, top to bottom, in screen
    pixels - `origin` is where the image's top-left corner is on screen.

    Pure apart from reading pixels, so it is tested against a real
    screenshot of the user's FL Studio rather than against a description.
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    px = rgb.load()
    hits: "dict[int, list]" = {}
    for y in range(height):
        lum = [_luminance(px[x, y]) for x in range(width)]
        borders = [x for x in range(2, width - 2) if lum[x] < min(lum[x - 2], lum[x + 2]) - 6]
        buttons = [
            (a, b, sum(lum[a + 2:b - 1]) / max(1, b - a - 3))
            for a, b in zip(borders, borders[1:])
            if 7 <= b - a <= 13
        ]
        for i in range(len(buttons) - STEPS + 1):
            run = buttons[i:i + STEPS]
            pitches = [q[0] - p[0] for p, q in zip(run, run[1:])]
            spaces = [q[0] - p[1] for p, q in zip(run, run[1:])]
            if (12 <= min(pitches) and max(pitches) <= 24 and max(pitches) - min(pitches) <= 2
                    and min(spaces) >= 3):
                centres = tuple((a + b) / 2 for a, b, _ in run)
                hits.setdefault(round(centres[0]), []).append((y, centres, [l for *_, l in run]))
                break

    rows = []
    for column in hits.values():
        groups = [[column[0]]]
        for hit in column[1:]:
            if hit[0] - groups[-1][-1][0] <= 12:
                groups[-1].append(hit)
            else:
                groups.append([hit])
        for group in groups:
            # A real row of buttons is several pixels tall; a lone line that
            # happens to match is noise.
            if len(group) < 3:
                continue
            _, centres, lums = group[len(group) // 2]
            y = (group[0][0] + group[-1][0]) / 2
            rows.append(StepRow(
                y=origin[1] + y,
                xs=tuple(origin[0] + x for x in centres),
                lit=tuple(l > LIT_LUMINANCE for l in lums),
            ))
    rows.sort(key=lambda r: r.y)
    if not rows:
        return rows
    # Only the channel rack: the column with the most rows. Anything else
    # that matched is somewhere else in the interface.
    rack_x = max({round(r.xs[0]) for r in rows},
                 key=lambda x: sum(1 for r in rows if abs(r.xs[0] - x) <= 2))
    return [r for r in rows if abs(r.xs[0] - rack_x) <= 2]


def capture(window: "tuple[int, int, int, int]"):
    """A screenshot of the window, and the screen position of its corner."""
    from PIL import ImageGrab

    left, top, width, height = window
    image = ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True)
    return image, (left, top)


VK_F6 = 0x75
VK_L = 0x4C


def see_channel_rack(window: "tuple[int, int, int, int]", needed: int) -> "list[StepRow]":
    """The channel rack's rows, bringing the rack to the front first if it
    cannot be seen - at least `needed` rows, or whatever was found last.

    F6 is FL Studio's own key for the channel rack, and a toggle: it
    raises a rack that is hidden or behind the playlist, and hides one that
    is already in front. So it is pressed only after looking, and looked
    again after each press, rather than pressed blind.
    """
    from heypeer.executor import cursor_control

    rows: "list[StepRow]" = []
    for attempt in range(3):
        image, origin = capture(rack_rect() or window)
        rows = find_step_rows(image, origin)
        if len(rows) >= needed or attempt == 2:
            return rows
        cursor_control.press_key(VK_F6)
        time.sleep(0.6)
    return rows


def demo_rows() -> "tuple[int, int]":
    """Which channel-rack rows the two composed parts go into, counted from
    0 at the top. HEYPEER_FL_ROWS="7,8" for a project whose drums are not
    its first two channels; the first two otherwise."""
    import os

    raw = os.environ.get("HEYPEER_FL_ROWS") or ""
    try:
        first, second = (int(part) for part in raw.split(","))
        return (first, second)
    except ValueError:
        return (ROW_FIRST, ROW_SECOND)


def pattern_moves(
    rows: "list[StepRow]", pattern: "dict | None" = None,
    targets: "tuple[int, int] | None" = None,
) -> "list[tuple[int, int, str]]":
    """The clicks that lay `pattern` into the two target rows, as
    `(x, y, button)`: first a right click on every lit step - FL Studio's
    own way to clear one - then a left click on every step of the pattern.

    Cleared and redrawn rather than corrected in place: a run that found
    the previous run's pattern already there clicked nothing at all, and
    on stage that is the drums not being written. Empty when the rows are
    not there to click.
    """
    pattern = pattern or PATTERN
    targets = targets or demo_rows()
    if max(targets) >= len(rows):
        return []
    clears, lights = [], []
    for key, index in zip((ROW_FIRST, ROW_SECOND), targets):
        row = rows[index]
        y = round(row.y)
        clears += [(round(row.xs[s]), y, "right") for s in range(STEPS) if row.lit[s]]
        lights += [(round(row.xs[s]), y, "left") for s in sorted(set(pattern.get(key, ())))
                   if 0 <= s < STEPS]
    return clears + lights


def maximize_window() -> bool:
    """Maximises FL Studio, so the channel rack is where the project put it
    rather than squeezed by whatever size the window last had."""
    try:
        import uiautomation as auto

        window = _main_window()
        if not window.Exists(maxSearchSeconds=1):
            return False
        window.GetWindowPattern().SetWindowVisualState(auto.WindowVisualState.Maximized)
        time.sleep(0.5)
        return True
    except Exception:
        return False


def _main_window():
    import uiautomation as auto

    return auto.WindowControl(searchDepth=1, SubName="FL Studio")


def dismiss_load_problems(wait: float = 0.0) -> bool:
    """Closes "Problems loading the project" - the missing-plugins list a
    downloaded project opens with - and returns whether there was one.

    Left open, it sits over the channel rack, takes the keys meant for the
    transport, and keeps the rack folded to two rows until it goes. It is a
    form inside the main window (`TMissingPluginsForm`), not a window of
    its own, and neither Escape nor Enter closes it - measured - so its Ok
    button is clicked: the leftmost of the three along its bottom edge.
    `wait` is how long to give it to appear, since it comes up after the
    window does.
    """
    try:
        from heypeer.executor import cursor_control

        dialog = _main_window().PaneControl(searchDepth=1, ClassName="TMissingPluginsForm")
        if not dialog.Exists(maxSearchSeconds=max(wait, 0.5)):
            return False
        rect = dialog.BoundingRectangle
        cursor_control.click_at(rect.left + round(0.524 * rect.width()), rect.bottom - 28)
        time.sleep(1.0)
        return True
    except Exception:
        return False


def dismiss_update_prompt() -> bool:
    """Closes FL Studio's "A newer version is available" prompt, ticking
    "Don't ask this in the future" so it does not come back, and returns
    whether there was one. Like the missing-plugins list it is a form inside
    the main window (`TMsgForm`) that Escape does not close - measured - so
    its controls are clicked: the tick box at its bottom left, then Cancel,
    the rightmost button."""
    try:
        from heypeer.executor import cursor_control

        prompt = _main_window().PaneControl(searchDepth=1, ClassName="TMsgForm")
        if not prompt.Exists(maxSearchSeconds=0.5) or "Update" not in (prompt.Name or ""):
            return False
        r = prompt.BoundingRectangle
        cursor_control.click_at(r.left + 13, r.bottom - 76)
        time.sleep(0.3)
        cursor_control.click_at(r.left + round(0.916 * r.width()), r.bottom - 28)
        time.sleep(0.6)
        return True
    except Exception:
        return False


def close_plugins_over_rack() -> int:
    """Closes plugin windows lying over the channel rack, and returns how
    many. A project reopens with the plugin windows it was saved with; in a
    window narrower than the screen they land on the rack and hide the
    steps. Each has its close button at its top right."""
    try:
        from heypeer.executor import cursor_control

        rack = rack_rect()
        if rack is None:
            return 0
        left, top, width, height = rack
        closed = 0
        for _ in range(12):
            over = [p for pane in _main_window().GetChildren() for p in pane.GetChildren()
                    if p.ClassName == "TPluginForm"
                    and p.BoundingRectangle.left < left + width and left < p.BoundingRectangle.right
                    and p.BoundingRectangle.top < top + height and top < p.BoundingRectangle.bottom]
            if not over:
                break
            r = over[0].BoundingRectangle
            cursor_control.click_at(r.right - 13, r.top + 13)
            time.sleep(0.35)
            closed += 1
        return closed
    except Exception:
        return 0


def rack_rect() -> "tuple[int, int, int, int] | None":
    """The channel rack's own rectangle, from the accessibility tree - FL
    Studio exposes its forms there even though it exposes nothing inside
    them. Looking only there keeps the search off the playlist."""
    try:
        rack = _main_window().PaneControl(searchDepth=2, ClassName="TStepSeqForm")
        if not rack.Exists(maxSearchSeconds=0.5):
            return None
        r = rack.BoundingRectangle
        return (r.left, r.top, r.width(), r.height()) if r.width() > 0 else None
    except Exception:
        return None


def song_mode(window: "tuple[int, int, int, int]") -> "bool | None":
    """Whether the transport is in SONG mode, read off the PAT/SONG switch
    at the top left of the toolbar - whichever half is lit is the mode.
    None when the switch is not where it was measured.

    Measured on the user's FL Studio 21, maximised: the switch's two halves
    are centred near (361, 11) and (361, 27), the lit one green.
    """
    try:
        image, _ = capture((window[0] + 345, window[1] + 4, 34, 30))
        rgb = image.convert("RGB")

        def green(y: int) -> float:
            pixels = [rgb.getpixel((x, y)) for x in range(4, 30)]
            return sum(g - (r + b) / 2 for r, g, b in pixels) / len(pixels)

        pat, song = green(7), green(23)
        if abs(pat - song) < 15:
            return None
        return song > pat
    except Exception:
        return None


def tempo_from_project(path: "str | None") -> "int | None":
    """The tempo saved in an .flp, or None.

    FL Studio does not put the tempo in its window title, which is where
    `read_tempo` looks, so for a known project the file is the honest
    source. An .flp is a "FLhd" header and a "FLdt" chunk of events, each an
    id byte followed by data whose size the id implies: below 64 one byte,
    below 128 two, below 192 four, above that a varint length. Event 156
    holds the tempo in thousandths of a BPM; projects older than FL Studio
    20 (the user's demo project is one) have only event 66, whole BPM.
    """
    if not path:
        return None
    try:
        data = open(path, "rb").read()
    except OSError:
        return None
    start = data.find(b"FLdt")
    if not data.startswith(b"FLhd") or start < 0:
        return None
    i = start + 8
    legacy = None
    while i < len(data):
        event = data[i]
        i += 1
        if event < 64:
            i += 1
        elif event < 128:
            if event == 66 and legacy is None:
                legacy = int.from_bytes(data[i:i + 2], "little")
            i += 2
        elif event < 192:
            if event == 156 and i + 4 <= len(data):
                tempo = round(int.from_bytes(data[i:i + 4], "little") / 1000)
                return tempo if 40 <= tempo <= 220 else None
            i += 4
        else:
            size, shift = 0, 0
            while i < len(data):
                byte = data[i]
                i += 1
                size |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            i += size
    return legacy if legacy is not None and 40 <= legacy <= 220 else None


def read_tempo() -> int:
    """FL Studio's current tempo, or a sensible default.

    Read from the window title where FL Studio puts it, falling back to 126
    - a tempo that suits the widest range of styles, so a failed read
    produces a plausible pattern rather than a strange one.
    """
    import re

    try:
        import uiautomation as auto

        window = auto.WindowControl(searchDepth=1, SubName="FL Studio")
        if window.Exists(maxSearchSeconds=1):
            match = re.search(r"(\d{2,3})\s*BPM", window.Name or "", re.IGNORECASE)
            if match:
                tempo = int(match.group(1))
                if 40 <= tempo <= 220:
                    return tempo
    except Exception:
        pass
    return 126


def window_rect() -> "tuple[int, int, int, int] | None":
    """Where FL Studio goes on the stage screen, from HEYPEER_FL_WINDOW -
    "left,top,width,height" relative to the stage - or None to maximise.

    The step finds the channel rack in a screenshot of it, so any size
    works that shows the whole rack: in the user's project it floats at
    about 290-790 px across and 82-570 down, so roughly 800 x 600 is the
    floor. A third of a 1920 screen, 640 wide, cuts it off; half fits.
    """
    import os

    raw = os.environ.get("HEYPEER_FL_WINDOW") or ""
    try:
        left, top, width, height = (int(part) for part in raw.split(","))
    except ValueError:
        return None
    from heypeer.tray.overlay import stage_rect

    stage_left, stage_top, _, _ = stage_rect()
    return (stage_left + left, stage_top + top, width, height)


def place_window() -> bool:
    """Puts FL Studio where `window_rect` says, or maximises it."""
    rect = window_rect()
    if rect is None:
        return maximize_window()
    try:
        from heypeer.executor.foreground import raise_window

        window = _main_window()
        if not window.Exists(maxSearchSeconds=1):
            return False
        raise_window(window.NativeWindowHandle, stage=rect, maximize=False)
        return True
    except Exception:
        return False


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

        from heypeer.executor.foreground import raise_window

        window = auto.WindowControl(searchDepth=1, SubName="FL Studio")
        if not window.Exists(maxSearchSeconds=1):
            return False
        # Restored and raised the robust way - plain SetActive left a
        # minimised FL Studio in the taskbar, and the step then searched a
        # screenshot of whatever was on screen for the channel rack.
        # Not maximised here: that undid the size HEYPEER_FL_WINDOW set,
        # and the window jumped to full screen when playback started.
        raise_window(window.NativeWindowHandle, maximize=window_rect() is None)
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


def launch(project: "str | None" = None) -> bool:
    """Starts FL Studio if it is not already running, and returns whether a
    window is there to click into afterwards.

    With `project`, that file is opened - through its file association, so
    whichever FL Studio the machine opens .flp files with - and the wait is
    the longer one a project with plugins needs to load.
    """
    if find_window() is not None:
        return True
    try:
        if project:
            import os

            os.startfile(project)  # noqa: S606 - Windows only, a file we were given
        else:
            from heypeer.executor import apps

            app = apps.resolve_app("fl studio")
            if app is None:
                return False
            apps.launch(app)
    except Exception:
        return False

    deadline = time.time() + (PROJECT_WAIT_SECONDS if project else LAUNCH_WAIT_SECONDS)
    while time.time() < deadline:
        if find_window() is not None:
            # The window exists before the project has finished loading
            # into it; clicking now lands on a half-drawn channel rack.
            time.sleep(PROJECT_SETTLE_SECONDS if project else 0)
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
