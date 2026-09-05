"""Timers and reminders - see `heypeer/executor/reminders.py`.

Durations here are tiny (hundredths of a second) so the suite stays fast
while still exercising the real `threading.Timer` path rather than a mock of
it: what is being tested is that a reminder actually fires on its own,
which a patched timer would assert nothing about.
"""

import threading
import time

from heypeer.executor.reminders import (
    MAX_ACTIVE,
    ReminderStore,
    format_clock,
    format_duration,
)


def test_a_reminder_fires_on_its_own() -> None:
    fired = threading.Event()
    store = ReminderStore(on_fire=lambda reminder: fired.set())
    store.add("les pâtes", 0.05)
    assert fired.wait(timeout=2.0), "reminder never fired"


def test_the_fired_reminder_carries_its_label_and_language() -> None:
    seen = []
    store = ReminderStore(on_fire=seen.append)
    store.add("les pâtes", 0.05, language="fr")
    time.sleep(0.3)
    assert len(seen) == 1
    assert seen[0].label == "les pâtes"
    assert seen[0].language == "fr"


def test_a_fired_reminder_is_no_longer_active() -> None:
    store = ReminderStore(on_fire=lambda r: None)
    store.add("x", 0.05)
    time.sleep(0.3)
    assert store.active() == []


def test_cancelled_reminders_never_fire() -> None:
    fired = threading.Event()
    store = ReminderStore(on_fire=lambda r: fired.set())
    reminder = store.add("les pâtes", 0.4)
    assert store.cancel(reminder.id) is not None
    assert not fired.wait(timeout=0.8), "a cancelled reminder went off anyway"


def test_cancel_matching_finds_a_reminder_by_a_loose_label() -> None:
    """The user says "annule le minuteur des pâtes" for one stored as
    "pâtes" - requiring the exact words back is what makes assistants feel
    stupid."""
    store = ReminderStore()
    store.add("pâtes", 30)
    assert store.cancel_matching("le minuteur des pâtes") is not None
    assert store.active() == []


def test_cancel_matching_ignores_an_unrelated_label() -> None:
    store = ReminderStore()
    store.add("pâtes", 30)
    assert store.cancel_matching("la lessive") is None
    assert len(store.active()) == 1


def test_cancel_matching_on_an_empty_label_matches_nothing() -> None:
    """Otherwise an empty string would match every label by substring."""
    store = ReminderStore()
    store.add("pâtes", 30)
    assert store.cancel_matching("   ") is None
    assert len(store.active()) == 1


def test_active_is_ordered_soonest_first() -> None:
    store = ReminderStore()
    store.add("later", 30)
    store.add("sooner", 5)
    assert [r.label for r in store.active()] == ["sooner", "later"]


def test_next_due_is_the_soonest_and_none_when_empty() -> None:
    store = ReminderStore()
    assert store.next_due() is None
    store.add("later", 30)
    store.add("sooner", 5)
    assert store.next_due().label == "sooner"


def test_the_store_refuses_to_become_a_task_manager() -> None:
    store = ReminderStore()
    for i in range(MAX_ACTIVE):
        assert store.add(f"t{i}", 30) is not None
    assert store.add("one too many", 30) is None


def test_cancel_all_reports_how_many_it_cancelled() -> None:
    store = ReminderStore()
    store.add("a", 30)
    store.add("b", 30)
    assert store.cancel_all() == 2
    assert store.active() == []


def test_remaining_never_goes_negative() -> None:
    store = ReminderStore(on_fire=lambda r: None)
    reminder = store.add("x", 0.01)
    time.sleep(0.2)
    assert reminder.remaining() == 0.0


def test_clear_stops_everything_pending() -> None:
    fired = threading.Event()
    store = ReminderStore(on_fire=lambda r: fired.set())
    store.add("a", 0.4)
    store.add("b", 0.4)
    store.clear()
    assert not fired.wait(timeout=0.8)


def test_a_store_with_no_callback_does_not_crash_when_one_fires() -> None:
    store = ReminderStore()
    store.add("x", 0.05)
    time.sleep(0.3)
    assert store.active() == []


def test_format_duration_speaks_french_agreement() -> None:
    assert format_duration(60) == "une minute"
    assert format_duration(120) == "2 minutes"
    assert format_duration(3600) == "une heure"
    assert format_duration(1) == "une seconde"


def test_format_duration_drops_seconds_next_to_hours() -> None:
    """"une heure 30 et 12 secondes" is not how anyone says it."""
    assert format_duration(3600 + 30 * 60 + 12) == "une heure 30 minutes"


def test_format_duration_english() -> None:
    assert format_duration(60, "en") == "1 minute"
    assert format_duration(150, "en") == "2 minutes 30 seconds"


def test_format_duration_of_nothing() -> None:
    assert format_duration(0) == "zéro seconde"
    assert format_duration(0, "en") == "0 seconds"


def test_format_clock_is_the_digital_form() -> None:
    assert format_clock(0) == "0:00"
    assert format_clock(62) == "1:02"
    assert format_clock(600) == "10:00"
    assert format_clock(3725) == "1:02:05"


def test_format_clock_floors_at_zero() -> None:
    assert format_clock(-5) == "0:00"
