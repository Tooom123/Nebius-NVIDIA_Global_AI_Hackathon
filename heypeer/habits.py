"""Noticing that the user keeps asking for the same thing, and offering to
make it a routine.

## Why this is not the monitoring that was deleted

Hey Peer once watched mouse and keyboard activity globally, learned
repeated sequences and offered them back as replayable "skills". That was
removed (see `main.py`'s module docstring) for three specific reasons, and
this design exists to have none of them:

* **It slowed the machine down.** The root cause was found and recorded at
  the time: the watcher polled the active window on *every* keypress, and
  each poll went through Win32 plus a process lookup - one system query per
  typed character. There are no input hooks here at all. What is observed
  is what Hey Peer itself did, recorded in the same function that already
  dispatched it, at a cost of appending to a list a few times a day.
* **The learned skills never matched a spoken instruction.** They were
  sequences of clicks and keystrokes, and nothing a user says resolves to
  those. What is recorded here is *the instruction*, in the user's own
  words - so a suggestion is made of the same material a routine is made
  of, and matching is not part of the problem.
* **They bloated every prompt.** Nothing here reaches the prompt. A
  suggestion is spoken once when it is noticed, and if accepted it becomes
  an ordinary named routine, which contributes only its name.

## What counts as a habit

The same instruction, in the same shape, several times, over days rather
than minutes. Deliberately strict, because the cost of the two errors is
not symmetric: a missed habit costs nothing - the user carries on saying
the sentence, as they already do - while a wrong suggestion interrupts them
to propose something they never wanted, which is the behaviour that makes
assistants annoying enough to turn off.

Repeats within one sitting are ignored for the same reason. Saying "monte
le son" four times in a row is one intention, badly served; suggesting a
routine for it would be answering "you keep asking for this" with "shall I
make it easier to ask?".

## Why a suggestion is offered once and then dropped

If the user says no, the habit is marked declined and never raised again.
An assistant that asks a second time has not understood the answer, and one
that asks weekly is a notification system.
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from heypeer.paths import user_data

DEFAULT_PATH = user_data("habits.json")

# How many times the same instruction has to be asked before it is worth
# mentioning. Three is the smallest number that is a pattern rather than a
# coincidence; two is "the user did a thing twice", which happens all day.
REPEATS_NEEDED = 3

# ...on at least this many separate days. This is what stops a burst of
# repeats in one sitting - the single most common shape of "same
# instruction several times" - from reading as a habit.
DAYS_NEEDED = 2

# Nothing older than this counts. A habit from two months ago that stopped
# is not a habit any more, and suggesting it would be describing the user
# to themselves inaccurately.
WINDOW_DAYS = 30

# Actions worth noticing. Deliberately a list rather than everything: no
# suggestion should ever be built out of "annule", "reply" or a question,
# and a routine made of read-only actions ("qu'est-ce qu'il y a sur mon
# ecran ?") saves nobody anything.
WORTH_NOTICING = {
    "move_file",
    "rename_file",
    "create_folder",
    "open_app",
    "play_music",
    "adjust_volume",
    "adjust_brightness",
    "maximize_window",
    "minimize_window",
    "close_window",
    "minimize_all",
    "search_web",
    "summarize_document",
    "set_reminder",
    "click_element",
    "general_task",
}

MAX_ENTRIES = 400


@dataclass
class Observation:
    """One thing Hey Peer did, and when."""

    action: str
    instruction: str
    at: str  # ISO 8601, UTC


@dataclass
class Habit:
    """A repeated instruction worth offering to make into a routine."""

    instruction: str
    action: str
    count: int
    days: int


def _resolve(path: "Path | None") -> Path:
    """Resolved inside each function rather than as a default argument
    value - a default binds once at import, which silently defeats a test
    patching DEFAULT_PATH afterwards. Found for real in `memory.py`."""
    return path if path is not None else DEFAULT_PATH


def _load_raw(path: Path) -> dict:
    if not path.is_file():
        return {"observations": [], "declined": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"observations": [], "declined": []}
    if not isinstance(data, dict):
        return {"observations": [], "declined": []}
    data.setdefault("observations", [])
    data.setdefault("declined", [])
    return data


def _save_raw(data: dict, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # a habits file that cannot be written must not break a turn


def _normalise(instruction: str) -> str:
    """The form two utterances are compared in.

    Case and surrounding punctuation only. Deliberately not stemming or
    fuzzy matching: "range la facture dans Archives" and "range la photo
    dans Archives" are different instructions about different files, and a
    matcher loose enough to merge them would suggest a routine that moves
    the wrong thing.
    """
    return " ".join(instruction.lower().strip().strip(".!?").split())


def record(action: str, instruction: str, path: "Path | None" = None) -> None:
    """Notes that Hey Peer carried out `instruction`.

    Called from the dispatch path, after the action succeeded. Silent and
    best-effort: this is bookkeeping, and no failure here is worth
    interrupting a turn the user asked for.
    """
    if action not in WORTH_NOTICING:
        return
    instruction = (instruction or "").strip()
    if not instruction:
        return

    path = _resolve(path)
    data = _load_raw(path)
    data["observations"].append(
        asdict(Observation(action=action, instruction=instruction,
                           at=datetime.now(timezone.utc).isoformat()))
    )
    data["observations"] = data["observations"][-MAX_ENTRIES:]
    _save_raw(data, path)


def _recent(data: dict, now: datetime) -> "list[dict]":
    cutoff = now - timedelta(days=WINDOW_DAYS)
    recent = []
    for entry in data.get("observations", []):
        if not isinstance(entry, dict) or not entry.get("instruction"):
            continue
        try:
            when = datetime.fromisoformat(entry["at"])
        except (ValueError, KeyError, TypeError):
            continue
        if when >= cutoff:
            recent.append({**entry, "_when": when})
    return recent


def detect(path: "Path | None" = None, now: "datetime | None" = None) -> "Habit | None":
    """The strongest habit worth suggesting, or None.

    One at a time on purpose: a suggestion interrupts, and offering three
    at once is a menu rather than an observation.
    """
    path = _resolve(path)
    data = _load_raw(path)
    now = now or datetime.now(timezone.utc)
    declined = {_normalise(d) for d in data.get("declined", []) if isinstance(d, str)}

    grouped: "dict[str, list[dict]]" = {}
    for entry in _recent(data, now):
        key = _normalise(entry["instruction"])
        if key and key not in declined:
            grouped.setdefault(key, []).append(entry)

    best = None
    for entries in grouped.values():
        if len(entries) < REPEATS_NEEDED:
            continue
        days = len({e["_when"].date() for e in entries})
        if days < DAYS_NEEDED:
            continue
        # The instruction is spoken back, so use the wording the user
        # actually said most often rather than the normalised key.
        wording = Counter(e["instruction"] for e in entries).most_common(1)[0][0]
        habit = Habit(
            instruction=wording,
            action=entries[-1]["action"],
            count=len(entries),
            days=days,
        )
        if best is None or (habit.count, habit.days) > (best.count, best.days):
            best = habit
    return best


def decline(instruction: str, path: "Path | None" = None) -> None:
    """Records that the user said no, so it is never suggested again.

    Asking twice has not understood the answer; asking weekly is a
    notification system.
    """
    path = _resolve(path)
    data = _load_raw(path)
    key = _normalise(instruction)
    if key and key not in {_normalise(d) for d in data.get("declined", [])}:
        data["declined"].append(instruction)
        _save_raw(data, path)


def accept(instruction: str, path: "Path | None" = None) -> None:
    """Records that the habit became a routine, so it is not suggested
    again either - it already exists."""
    decline(instruction, path)


def clear(path: "Path | None" = None) -> None:
    """Forgets everything observed. Not wired to a spoken action yet; it
    exists so the data is not a thing only a text editor can undo."""
    _save_raw({"observations": [], "declined": []}, _resolve(path))
