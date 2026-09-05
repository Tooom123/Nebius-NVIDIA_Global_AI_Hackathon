"""Named routines: one phrase that runs several actions.

"lance ma routine du matin" -> open Spotify, read out the timers, say the
weather. Alexa's most-used power feature, and the hackathon track's
"reusable skills" in the form that actually works for a voice assistant.

## Why this is not the skills feature that was deleted

Hey Peer previously watched mouse and keyboard activity, learned repeated
sequences, and offered them back as replayable "skills". That was removed
(see `main.py`'s module docstring) for three reasons: the learned skills
never matched a spoken instruction, they bloated every prompt, and the
global input hooks feeding them cost real performance.

This is the same idea with the failure modes designed out, not a retry:

* Routines are *told*, never inferred. "quand je dis X, fais Y et Z" - so
  there is nothing to match against, because the user named the trigger
  themselves. That was the fatal flaw of the learned version.
* They are stored as a list of instructions in Hey Peer's own words, not as
  coordinates and keystrokes. Replaying "open Spotify" survives a window
  moving; replaying "click at (840, 210)" does not.
* Only the names are given to the model each turn, not the bodies - one
  short line however many steps a routine has, so the prompt cannot grow
  the way the old one did.
* No input hooks at all, so none of the performance cost.

## Why steps are re-interpreted rather than stored as intents

A step is stored as the sentence the user said ("mets de la musique"), and
run by feeding it back through the ordinary interpret-and-dispatch path.
Storing resolved intents instead would freeze each step against the world
as it was when the routine was recorded - a filename that has since moved,
an app that was not installed yet. Re-interpreting costs one model call per
step and keeps a routine meaningful as things change around it.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "routines.json"

# A routine is a handful of steps someone can hold in their head, not a
# script. Past this it wants a file and an editor, not a voice assistant.
MAX_STEPS = 8
MAX_ROUTINES = 20


@dataclass(frozen=True)
class Routine:
    """`name` is what the user calls it, lowercased for matching but spoken
    back as stored. `steps` are instructions in the user's own words."""

    name: str
    steps: "list[str]"


def _resolve(path: "Path | None") -> Path:
    """Resolved inside each function rather than as a default argument
    value: a default is bound once at import, which silently defeats any
    test patching `DEFAULT_PATH` afterwards. That exact bug was found for
    real in `heypeer/memory.py` - the write went to the real file instead of
    the fixture - so this module was written this way from the start."""
    return path if path is not None else DEFAULT_PATH


def load(path: "Path | None" = None) -> "list[Routine]":
    """Every stored routine, or `[]` if there are none or the file cannot be
    read. A broken routines file must never block an ordinary turn."""
    path = _resolve(path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    routines = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        steps = entry.get("steps")
        if isinstance(name, str) and isinstance(steps, list):
            clean = [s for s in steps if isinstance(s, str) and s.strip()]
            if name.strip() and clean:
                routines.append(Routine(name=name.strip(), steps=clean[:MAX_STEPS]))
    return routines


def save(routines: "list[Routine]", path: "Path | None" = None) -> None:
    path = _resolve(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in routines], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember(name: str, steps: "list[str]", path: "Path | None" = None) -> "Routine | None":
    """Stores a routine, replacing any existing one of the same name.

    Returns None if the name or steps are empty, or if there are already
    `MAX_ROUTINES` different ones - so the caller can say so rather than
    silently doing nothing. Replacing rather than refusing a duplicate name
    is deliberate: "en fait ma routine du matin c'est plutot..." is a
    correction, and making the user delete first would be pedantry."""
    name = name.strip()
    clean = [s.strip() for s in steps if s and s.strip()][:MAX_STEPS]
    if not name or not clean:
        return None
    existing = [r for r in load(path) if r.name.casefold() != name.casefold()]
    if len(existing) >= MAX_ROUTINES:
        return None
    routine = Routine(name=name, steps=clean)
    existing.append(routine)
    save(existing, path)
    return routine


def find(name: str, path: "Path | None" = None) -> "Routine | None":
    """Matches loosely, like reminders do: the user says "lance ma routine
    du matin" for one stored as "matin". Exact matches win over partial
    ones, so a routine literally called "matin" is never shadowed by a
    longer name that happens to contain it."""
    needle = name.strip().casefold()
    if not needle:
        return None
    routines = load(path)
    for routine in routines:
        if routine.name.casefold() == needle:
            return routine
    for routine in routines:
        stored = routine.name.casefold()
        if needle in stored or stored in needle:
            return routine
    return None


def forget(name: str, path: "Path | None" = None) -> "Routine | None":
    routine = find(name, path)
    if routine is None:
        return None
    save([r for r in load(path) if r.name != routine.name], path)
    return routine


def names(path: "Path | None" = None) -> "list[str]":
    """Just the names - what is given to Nemotron as context every turn.

    The bodies are deliberately left out: this is the line that keeps
    routines from repeating the prompt-bloat failure of the deleted learned-
    skills feature. However many steps a routine has, it costs one short
    name here."""
    return [r.name for r in load(path)]
