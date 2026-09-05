"""Timers, reminders and alarms - the one thing every comparison of Siri,
Alexa and Google Assistant names as the feature people actually use daily,
and the one thing Hey Peer could not do at all.

## Why this needed new machinery rather than another action

Every other action in this project finishes inside the turn that asked for
it: a file moves, a window closes, a sentence is spoken, the exchange ends.
A reminder is the first thing Hey Peer does that *outlives its turn* and
then has to speak on its own, with no wake word and nobody having said
anything. That is a scheduler, and it needs an owner with a lifetime longer
than the exchange - `HeyPeer` holds one for the process.

## Why threading.Timer, and not a polling loop

One `threading.Timer` per pending reminder, cancelled if the reminder is.
The alternative - a loop waking every second to compare timestamps - costs
a wakeup a second forever to serve something that fires a handful of times
a day, on a machine where this app is meant to sit in the background
unnoticed. The countdown UI redraws on its own schedule while visible (see
`tray/countdown.py`); that is a separate, bounded cost that stops when the
timer does.

## Not persisted across restarts, deliberately

A timer is a promise about the next few minutes. Restoring "20 minutes"
that expired while the machine was off, and announcing it late, is worse
than dropping it - the user has already moved on, and a late alarm is a
bug, not a feature. Long-horizon reminders ("demain a 9h") are a different
product with different expectations, and would want the calendar
integration rather than this.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

# Enough to hold "pasta, eggs, and a 10-minute reminder to call back" at
# once without becoming a task manager. A voice assistant juggling fifty
# live timers is not a use case; it is a symptom.
MAX_ACTIVE = 10


@dataclass
class Reminder:
    """One pending timer. `label` is what the user called it ("les pates"),
    or empty for a bare "rappelle-moi dans 10 minutes"."""

    id: int
    label: str
    duration_seconds: float
    # Wall-clock deadline, from `time.monotonic` - immune to the system
    # clock being changed or drifting under us, which `time.time` is not.
    deadline: float
    language: str = "fr"
    _timer: "threading.Timer | None" = field(default=None, repr=False, compare=False)

    def remaining(self) -> float:
        """Seconds left, floored at zero - never negative, so callers
        formatting it don't have to special-case an overdue timer."""
        return max(0.0, self.deadline - time.monotonic())


class ReminderStore:
    """The set of live reminders, and the timers that fire them.

    Thread-safe: reminders are added from the turn-handling thread and fire
    on `threading.Timer`'s own threads, and the countdown UI reads them from
    a third.
    """

    def __init__(self, on_fire: "Callable[[Reminder], None] | None" = None) -> None:
        self._lock = threading.Lock()
        self._reminders: "dict[int, Reminder]" = {}
        self._next_id = 1
        # Called when a reminder comes due. Set by whoever can speak - this
        # module deliberately knows nothing about TTS.
        self.on_fire = on_fire

    def add(self, label: str, duration_seconds: float, language: str = "fr") -> "Reminder | None":
        """Schedules a reminder. Returns None if there are already
        `MAX_ACTIVE` live ones, so the caller can say so rather than
        silently dropping it."""
        with self._lock:
            if len(self._reminders) >= MAX_ACTIVE:
                return None
            reminder = Reminder(
                id=self._next_id,
                label=label,
                duration_seconds=duration_seconds,
                deadline=time.monotonic() + duration_seconds,
                language=language,
            )
            self._next_id += 1
            self._reminders[reminder.id] = reminder

        timer = threading.Timer(duration_seconds, self._fire, args=(reminder.id,))
        timer.daemon = True
        reminder._timer = timer
        timer.start()
        return reminder

    def _fire(self, reminder_id: int) -> None:
        """Runs on the timer's thread when a reminder comes due."""
        with self._lock:
            reminder = self._reminders.pop(reminder_id, None)
        if reminder is None:
            return  # cancelled between the timer firing and taking the lock
        if self.on_fire is not None:
            self.on_fire(reminder)

    def active(self) -> "list[Reminder]":
        """Live reminders, soonest first - the order a countdown should show
        them and the order "c'est quoi mes minuteurs ?" should read them."""
        with self._lock:
            return sorted(self._reminders.values(), key=lambda r: r.deadline)

    def next_due(self) -> "Reminder | None":
        reminders = self.active()
        return reminders[0] if reminders else None

    def cancel(self, reminder_id: int) -> "Reminder | None":
        with self._lock:
            reminder = self._reminders.pop(reminder_id, None)
        if reminder is not None and reminder._timer is not None:
            reminder._timer.cancel()
        return reminder

    def cancel_matching(self, label: str) -> "Reminder | None":
        """Cancels by what the user called it. Matched loosely on purpose:
        they say "annule le minuteur des pates" for a reminder stored as
        "pates", and having to repeat the exact words back is precisely the
        kind of brittleness that makes a voice assistant feel stupid."""
        needle = label.strip().casefold()
        if not needle:
            return None
        for reminder in self.active():
            haystack = reminder.label.casefold()
            if needle in haystack or haystack in needle:
                return self.cancel(reminder.id)
        return None

    def cancel_all(self) -> int:
        """Cancels every live reminder, returning how many there were - so
        the caller can say "j'ai annulé tes trois minuteurs"."""
        cancelled = 0
        for reminder in self.active():
            if self.cancel(reminder.id) is not None:
                cancelled += 1
        return cancelled

    def clear(self) -> None:
        """Cancels everything without reporting - used at shutdown so a
        pending timer can't fire into a half-torn-down app."""
        self.cancel_all()


def format_duration(seconds: float, language: str = "fr") -> str:
    """A spoken duration: "10 minutes", "1 heure 30", "45 secondes".

    Written out rather than passed to a date library because this is read
    aloud, not printed: "0:01:30" and "1 h 30 min" are both wrong out loud,
    and the French forms need agreement ("une heure", not "1 heure") that a
    generic formatter will not produce.
    """
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    english = language == "en"
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}" if english
                     else ("une heure" if hours == 1 else f"{hours} heures"))
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}" if english
                     else ("une minute" if minutes == 1 else f"{minutes} minutes"))
    # Seconds are noise next to hours - "1 heure 30 et 12 secondes" is not
    # how anyone says it - so they only survive on their own or beside minutes.
    if secs and not hours:
        parts.append(f"{secs} second{'s' if secs > 1 else ''}" if english
                     else ("une seconde" if secs == 1 else f"{secs} secondes"))
    if not parts:
        return "0 seconds" if english else "zéro seconde"
    return " ".join(parts)


def format_clock(seconds: float) -> str:
    """The countdown's own text: M:SS, or H:MM:SS past an hour. This one is
    *read*, not spoken, so the digital-clock form is right here."""
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
