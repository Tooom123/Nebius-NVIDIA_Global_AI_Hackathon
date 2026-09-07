"""Finding a control on screen by its name, through Windows UI Automation.

## Why the accessibility tree rather than a vision model

Clicky asks a vision model for pixel coordinates and flies a pointer there.
That is the only option on macOS at their layer, and it has two costs: the
model has to *see* the control clearly, and the answer is stale the moment
a window moves.

Windows exposes the same information exactly. UI Automation is the API
screen readers use: every button, menu item and field in a well-behaved
application is a node with a name and a `BoundingRectangle`. Asking it
"where is the button called Send" returns the real rectangle, in real pixel
coordinates, computed by the system rather than estimated from an image.

So this is not a cheaper version of the vision approach; it is a better
one. No screenshot, no model call, no latency, exact bounds, and it stays
correct when the window is dragged.

## Where it does not work

Applications that draw their own UI without an accessibility tree - games,
some Electron apps, canvas-based editors - expose nothing useful. `find`
returns None there rather than guessing, and the caller says so. Vision
remains the honest fallback for those, and is deliberately not built here:
`read_screen` already exists and a wrong click is worse than no click.

## Matching

Names are matched the way a person says them, not the way a developer
wrote them: case-insensitive, and a control whose name merely *contains*
what the user said counts. "Send" finds a button labelled "Send message".
Exact matches win over partial ones, so a literal "Send" is never shadowed
by "Send later" - the same rule `executor/routines.py` uses, for the same
reason.

## What is verified here

None of it, against real windows. `uiautomation` is a Windows-only package
and there is no Windows in this project's dev sandbox: the search, filter
and centre-point logic below are unit-tested against a fake tree, and
`is_available()` is real. Whether Chrome exposes a "Send" button under that
name is for the manual test plan.
"""

import platform

# How deep to walk. UI Automation trees are wide and shallow for real
# applications; going deeper mostly finds text runs inside labels, at
# increasing cost. Six levels covers window -> pane -> document -> group ->
# control -> inner control, which is where clickable things live.
MAX_DEPTH = 6

# Cap on how many nodes are examined. An unbounded walk of a large document
# can take seconds, and a voice assistant that pauses that long has already
# failed the interaction regardless of what it eventually finds.
MAX_NODES = 3000

# Control types worth clicking. Deliberately a list rather than "anything
# with a name": a window's title and a document's text also carry names,
# and matching those would return a rectangle covering half the screen.
CLICKABLE_TYPES = {
    "ButtonControl",
    "HyperlinkControl",
    "MenuItemControl",
    "ListItemControl",
    "TabItemControl",
    "CheckBoxControl",
    "RadioButtonControl",
    "SplitButtonControl",
    "TreeItemControl",
}


class Element:
    """A found control: what it is called, and where it is."""

    __slots__ = ("name", "control_type", "rect")

    def __init__(self, name: str, control_type: str, rect: "tuple[int, int, int, int]") -> None:
        self.name = name
        self.control_type = control_type
        self.rect = rect  # (left, top, right, bottom), screen pixels

    @property
    def center(self) -> "tuple[int, int]":
        """Where to click.

        The centre rather than a corner, because a bounding rectangle can
        include points that are not clickable - Microsoft's own
        documentation says so for irregular or partly obscured controls -
        and the centre is the likeliest point to be inside the real hit
        area.
        """
        left, top, right, bottom = self.rect
        return ((left + right) // 2, (top + bottom) // 2)

    @property
    def is_usable(self) -> bool:
        """Whether the rectangle is real. Collapsed or offscreen controls
        report degenerate bounds, and clicking their "centre" would press
        whatever happens to be at that point instead."""
        left, top, right, bottom = self.rect
        return right > left and bottom > top

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Element {self.name!r} {self.control_type} at {self.center}>"


def is_available() -> bool:
    """Whether UI Automation can be used at all."""
    if platform.system() != "Windows":
        return False
    try:
        import uiautomation  # noqa: F401
    except ImportError:
        return False
    return True


def _matches(name: str, needle: str) -> bool:
    return needle in name.casefold()


def collect(root, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> "list[Element]":
    """Every clickable, named control under `root`, breadth-first.

    Breadth-first rather than depth-first on purpose: the controls a user
    means are near the top of the tree - a toolbar button, a menu item -
    and a depth-first walk spends its node budget deep inside the first
    branch it enters, which is usually a document's text.
    """
    found: "list[Element]" = []
    queue = [(root, 0)]
    examined = 0

    while queue and examined < max_nodes:
        node, depth = queue.pop(0)
        if depth > max_depth:
            continue
        try:
            children = node.GetChildren()
        except Exception:
            children = []  # a window closing mid-walk must not raise
        for child in children:
            # Counted per child rather than per dequeued node: a single
            # parent with a thousand children is one dequeue and a thousand
            # BoundingRectangle reads, which is where the time actually
            # goes. Counting dequeues let exactly that case run unbounded.
            if examined >= max_nodes:
                break
            examined += 1
            try:
                name = (child.Name or "").strip()
                control_type = getattr(child, "ControlTypeName", "")
                if name and control_type in CLICKABLE_TYPES:
                    rect = child.BoundingRectangle
                    element = Element(
                        name,
                        control_type,
                        (rect.left, rect.top, rect.right, rect.bottom),
                    )
                    if element.is_usable:
                        found.append(element)
            except Exception:
                continue  # one unreadable node must not lose the rest
            queue.append((child, depth + 1))

    return found


def pick(elements: "list[Element]", spoken_name: str) -> "Element | None":
    """The element `spoken_name` most likely means, or None.

    Exact match first, then the shortest containing one. Shortest because a
    control named exactly what was said is the best answer, and failing
    that the least-padded name is the closest - "Send" should find "Send"
    over "Send and archive later".
    """
    needle = spoken_name.strip().casefold()
    if not needle:
        return None

    for element in elements:
        if element.name.casefold() == needle:
            return element

    partial = [e for e in elements if _matches(e.name, needle)]
    if not partial:
        return None
    return min(partial, key=lambda e: len(e.name))


def find(spoken_name: str, window_title: "str | None" = None) -> "Element | None":
    """Finds a clickable control by name, in the foreground window or in
    the one whose title matches `window_title`.

    Returns None rather than raising for every failure - not Windows, no
    accessibility tree, nothing matching - because the caller's response is
    the same sentence in all of those cases, and the difference matters to
    a log rather than to the user.
    """
    if not is_available():
        return None
    try:
        import uiautomation as auto

        root = (
            auto.WindowControl(searchDepth=2, SubName=window_title)
            if window_title
            else auto.GetForegroundControl()
        )
        if root is None:
            return None
        return pick(collect(root), spoken_name)
    except Exception:
        return None
