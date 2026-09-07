"""Habit detection - see `heypeer/habits.py`.

Every test passes an explicit path into tmp_path. The real store lives in
the project's own data/, and a test writing there would both pollute the
developer's history and pass for the wrong reason - a mistake this project
has already made once, in memory.py.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from heypeer import habits


def _at(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _seed(path: Path, entries) -> None:
    import json

    path.write_text(
        json.dumps({
            "observations": [
                {"action": a, "instruction": i, "at": t} for a, i, t in entries
            ],
            "declined": [],
        }),
        encoding="utf-8",
    )


# --- what gets recorded ---

def test_an_ordinary_action_is_recorded(tmp_path: Path) -> None:
    store = tmp_path / "habits.json"
    habits.record("move_file", "range la facture dans Archives", store)
    assert len(habits._load_raw(store)["observations"]) == 1


def test_conversation_and_undo_are_not_recorded(tmp_path: Path) -> None:
    """No suggestion should ever be built out of "annule" or small talk."""
    store = tmp_path / "habits.json"
    for action in ("reply", "ask", "undo", "unknown", "list_reminders"):
        habits.record(action, "quelque chose", store)
    assert habits._load_raw(store)["observations"] == []


def test_an_empty_instruction_is_not_recorded(tmp_path: Path) -> None:
    store = tmp_path / "habits.json"
    habits.record("move_file", "   ", store)
    assert habits._load_raw(store)["observations"] == []


def test_the_store_is_bounded(tmp_path: Path) -> None:
    store = tmp_path / "habits.json"
    for i in range(habits.MAX_ENTRIES + 50):
        habits.record("open_app", f"ouvre app{i}", store)
    assert len(habits._load_raw(store)["observations"]) == habits.MAX_ENTRIES


def test_a_corrupted_store_degrades_to_empty(tmp_path: Path) -> None:
    """A broken habits file must never block a turn."""
    store = tmp_path / "habits.json"
    store.write_text("{ not json", encoding="utf-8")
    assert habits.detect(store) is None


# --- what counts as a habit ---

def test_the_same_instruction_over_several_days_is_a_habit(tmp_path: Path) -> None:
    store = tmp_path / "habits.json"
    _seed(store, [
        ("move_file", "range la facture dans Archives", _at(0)),
        ("move_file", "range la facture dans Archives", _at(1)),
        ("move_file", "range la facture dans Archives", _at(3)),
    ])
    habit = habits.detect(store)
    assert habit is not None
    assert habit.instruction == "range la facture dans Archives"
    assert habit.count == 3


def test_repeats_in_one_sitting_are_not_a_habit(tmp_path: Path) -> None:
    """Saying "monte le son" four times in a row is one intention badly
    served - suggesting a routine would answer "you keep asking for this"
    with "shall I make it easier to ask?"."""
    store = tmp_path / "habits.json"
    _seed(store, [("adjust_volume", "monte le son", _at(0)) for _ in range(6)])
    assert habits.detect(store) is None


def test_two_repeats_are_not_enough(tmp_path: Path) -> None:
    """Two is "the user did a thing twice", which happens all day."""
    store = tmp_path / "habits.json"
    _seed(store, [
        ("open_app", "ouvre Slack", _at(0)),
        ("open_app", "ouvre Slack", _at(2)),
    ])
    assert habits.detect(store) is None


def test_an_old_habit_no_longer_counts(tmp_path: Path) -> None:
    """A habit that stopped two months ago is not a habit, and suggesting
    it would describe the user to themselves inaccurately."""
    store = tmp_path / "habits.json"
    _seed(store, [
        ("open_app", "ouvre Slack", _at(habits.WINDOW_DAYS + 5)),
        ("open_app", "ouvre Slack", _at(habits.WINDOW_DAYS + 6)),
        ("open_app", "ouvre Slack", _at(habits.WINDOW_DAYS + 7)),
    ])
    assert habits.detect(store) is None


def test_different_instructions_are_not_merged(tmp_path: Path) -> None:
    """"range la facture" and "range la photo" are different instructions
    about different files; a matcher loose enough to merge them would
    suggest a routine that moves the wrong thing."""
    store = tmp_path / "habits.json"
    _seed(store, [
        ("move_file", "range la facture dans Archives", _at(0)),
        ("move_file", "range la photo dans Archives", _at(1)),
        ("move_file", "range le contrat dans Archives", _at(2)),
    ])
    assert habits.detect(store) is None


def test_casing_and_trailing_punctuation_do_not_split_a_habit(tmp_path: Path) -> None:
    store = tmp_path / "habits.json"
    _seed(store, [
        ("open_app", "Ouvre Slack.", _at(0)),
        ("open_app", "ouvre slack", _at(1)),
        ("open_app", "ouvre Slack ", _at(2)),
    ])
    assert habits.detect(store) is not None


def test_the_strongest_habit_is_the_one_offered(tmp_path: Path) -> None:
    """One at a time: a suggestion interrupts, and three at once is a menu
    rather than an observation."""
    store = tmp_path / "habits.json"
    _seed(store, [
        ("open_app", "ouvre Slack", _at(0)),
        ("open_app", "ouvre Slack", _at(1)),
        ("open_app", "ouvre Slack", _at(2)),
        ("play_music", "mets du jazz", _at(0)),
        ("play_music", "mets du jazz", _at(1)),
        ("play_music", "mets du jazz", _at(2)),
        ("play_music", "mets du jazz", _at(3)),
    ])
    assert habits.detect(store).instruction == "mets du jazz"


# --- declining ---

def test_a_declined_habit_is_never_offered_again(tmp_path: Path) -> None:
    """An assistant that asks twice has not understood the answer."""
    store = tmp_path / "habits.json"
    _seed(store, [("open_app", "ouvre Slack", _at(i)) for i in range(3)])
    assert habits.detect(store) is not None
    habits.decline("ouvre Slack", store)
    assert habits.detect(store) is None


def test_declining_ignores_casing(tmp_path: Path) -> None:
    store = tmp_path / "habits.json"
    _seed(store, [("open_app", "Ouvre Slack", _at(i)) for i in range(3)])
    habits.decline("ouvre slack.", store)
    assert habits.detect(store) is None


def test_accepting_also_stops_it_being_offered(tmp_path: Path) -> None:
    """It is a routine now; suggesting it again would offer to create what
    already exists."""
    store = tmp_path / "habits.json"
    _seed(store, [("open_app", "ouvre Slack", _at(i)) for i in range(3)])
    habits.accept("ouvre Slack", store)
    assert habits.detect(store) is None


def test_clear_forgets_everything(tmp_path: Path) -> None:
    store = tmp_path / "habits.json"
    _seed(store, [("open_app", "ouvre Slack", _at(i)) for i in range(3)])
    habits.clear(store)
    assert habits.detect(store) is None
