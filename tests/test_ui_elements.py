"""Finding a control by name - see `heypeer/executor/ui_elements.py`.

`uiautomation` is Windows-only and absent here, so the tree walk is driven
against a fake. That covers the search, the filtering and the matching -
everything except whether a real application names its buttons the way a
person says them, which is for the manual test plan.
"""

from unittest.mock import MagicMock, patch

from heypeer.executor import ui_elements as ui


class _Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


def _node(name="", control_type="", rect=(0, 0, 10, 10), children=()):
    node = MagicMock()
    node.Name = name
    node.ControlTypeName = control_type
    node.BoundingRectangle = _Rect(*rect)
    node.GetChildren.return_value = list(children)
    return node


# --- geometry ---

def test_the_click_point_is_the_centre_of_the_control() -> None:
    """A bounding rectangle can contain points that are not clickable -
    Microsoft says so for irregular or obscured controls - and the centre
    is the likeliest to be inside the real hit area."""
    assert ui.Element("Send", "ButtonControl", (100, 200, 300, 240)).center == (200, 220)


def test_a_collapsed_control_is_not_usable() -> None:
    """Clicking a zero-area control's "centre" presses whatever is at that
    point instead."""
    assert ui.Element("x", "ButtonControl", (50, 50, 50, 50)).is_usable is False
    assert ui.Element("x", "ButtonControl", (50, 50, 40, 60)).is_usable is False
    assert ui.Element("x", "ButtonControl", (50, 50, 60, 60)).is_usable is True


# --- the tree walk ---

def test_only_clickable_named_controls_are_collected() -> None:
    """A window title and a document's text also have names; matching those
    would return a rectangle covering half the screen."""
    root = _node(children=[
        _node("Send", "ButtonControl", (0, 0, 80, 30)),
        _node("Gmail - Inbox", "WindowControl", (0, 0, 1900, 1000)),
        _node("Message body text", "TextControl", (0, 0, 800, 400)),
        _node("", "ButtonControl", (0, 0, 40, 40)),  # unnamed
    ])
    found = ui.collect(root)
    assert [e.name for e in found] == ["Send"]


def test_collapsed_controls_are_skipped() -> None:
    root = _node(children=[_node("Hidden", "ButtonControl", (10, 10, 10, 10))])
    assert ui.collect(root) == []


def test_nested_controls_are_found() -> None:
    root = _node(children=[
        _node("toolbar", "PaneControl", (0, 0, 500, 40), children=[
            _node("Reply", "ButtonControl", (10, 5, 70, 35)),
        ]),
    ])
    assert [e.name for e in ui.collect(root)] == ["Reply"]


def test_the_walk_respects_its_depth_limit() -> None:
    deep = _node("Deep", "ButtonControl", (0, 0, 10, 10))
    for _ in range(10):
        deep = _node("pane", "PaneControl", (0, 0, 100, 100), children=[deep])
    assert ui.collect(_node(children=[deep]), max_depth=2) == []


def test_the_walk_respects_its_node_budget() -> None:
    """An unbounded walk of a large document takes seconds, and a voice
    assistant that pauses that long has already failed the interaction."""
    many = [_node(f"b{i}", "ButtonControl", (0, 0, 10, 10)) for i in range(500)]
    found = ui.collect(_node(children=many), max_nodes=10)
    assert 0 < len(found) < 500


def test_a_window_closing_mid_walk_does_not_raise() -> None:
    broken = _node("gone", "PaneControl", (0, 0, 10, 10))
    broken.GetChildren.side_effect = RuntimeError("window closed")
    root = _node(children=[broken, _node("Send", "ButtonControl", (0, 0, 80, 30))])
    assert [e.name for e in ui.collect(root)] == ["Send"]


def test_one_unreadable_node_does_not_lose_the_others() -> None:
    bad = MagicMock()
    type(bad).Name = property(lambda self: (_ for _ in ()).throw(RuntimeError("gone")))
    root = _node(children=[bad, _node("Send", "ButtonControl", (0, 0, 80, 30))])
    assert [e.name for e in ui.collect(root)] == ["Send"]


# --- matching ---

def _els(*names):
    return [ui.Element(n, "ButtonControl", (0, 0, 10, 10)) for n in names]


def test_a_name_is_matched_the_way_a_person_says_it() -> None:
    assert ui.pick(_els("Send message"), "send").name == "Send message"
    assert ui.pick(_els("Send"), "SEND").name == "Send"


def test_an_exact_match_beats_a_longer_one() -> None:
    """A literal "Send" must never be shadowed by "Send later"."""
    assert ui.pick(_els("Send later", "Send", "Send and archive"), "Send").name == "Send"


def test_the_shortest_partial_wins_when_there_is_no_exact_match() -> None:
    assert ui.pick(_els("Send and archive later", "Send later"), "send").name == "Send later"


def test_nothing_matching_returns_none() -> None:
    assert ui.pick(_els("Reply", "Forward"), "Send") is None


def test_an_empty_name_matches_nothing() -> None:
    """Otherwise an empty string would match every control by substring."""
    assert ui.pick(_els("Send"), "   ") is None


# --- availability ---

def test_not_available_off_windows() -> None:
    with patch("platform.system", return_value="Linux"):
        assert ui.is_available() is False


def test_find_returns_none_rather_than_raising_when_unavailable() -> None:
    """The caller says the same sentence for every failure; the difference
    belongs in a log."""
    with patch.object(ui, "is_available", return_value=False):
        assert ui.find("Send") is None
