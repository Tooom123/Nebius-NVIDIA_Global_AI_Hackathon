"""Persistent memory: facts Hey Peer remembers about the user across
sessions, not just within one exchange.

## Why this exists

`HeyPeer._history` (see `main.py`) is a *conversation* memory - it holds
what was said in the current exchange and is dropped the moment the
exchange closes, by design, so the next "Hey Peer" starts clean. That is
the right behaviour for a conversation and the wrong one for "retiens que
je prefere qu'on m'appelle Tom": a fact told once should still be true next
week, on a fresh launch of the app, with no exchange open at all.

## Why this is a local file, not something dispatched to an external agent

Hermes Agent (`executor/general_agent.py`) has its own persistent memory
(`~/.hermes/state.db`), and it was tempting to lean on that instead of
building a second store. Rejected: Hermes is optional, gracefully absent if
not installed (see that module's own docstring) - and "always-on, private,
your data under your control" cannot be true of Hey Peer's *own* memory of
what the user told it if remembering a fact silently does nothing whenever
an unrelated external tool happens not to be on PATH. This has to work with
nothing installed beyond Hey Peer itself, the same as file actions do.

## What this is not

Not a vector store, not semantic search, not automatic inference from
conversation - all real memory-system designs, and all more than a voice
assistant remembering "the user prefers X" needs. Facts are told explicitly
("retiens que...") and read back the same way: a small bounded list,
included as plain text in every turn's context (see `NemotronClient.
interpret_text`'s `memory` parameter) so Nemotron can naturally refer to
one in an answer, the same way it already sees the watched folder's file
listing.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "memory.json"

# Bounded so an old, no-longer-relevant fact eventually falls off rather
# than accumulating forever and bloating every single prompt with things
# said months ago. There is no "forget this one fact" action yet - see the
# module docstring's own scope note - so this is also, today, the only way
# a stale fact stops being included.
MAX_FACTS = 50


@dataclass(frozen=True)
class Fact:
    text: str
    remembered_at: str  # ISO 8601, UTC


def load(path: "Path | None" = None) -> "list[Fact]":
    """Every remembered fact, oldest first - or `[]` if there is no memory
    file yet (a fresh install) or it cannot be read (corrupted by hand,
    disk full mid-write). A memory failure must never block an ordinary
    turn; an empty memory is the safe degradation.

    `path` defaults to `None`, resolved to `DEFAULT_PATH` *inside* the
    function rather than as `path: Path = DEFAULT_PATH` in the signature -
    a default argument value is bound once, at import time, so a test (or
    anything else) patching the module-level `DEFAULT_PATH` afterwards
    would silently have no effect on calls that rely on the default. Found
    live: a test patched `heypeer.memory.DEFAULT_PATH` to a temp path, and
    the write went to the real one anyway - the actual project's own
    `data/memory.json` on disk, not a fixture.
    """
    path = path if path is not None else DEFAULT_PATH
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    facts = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("text"), str):
            facts.append(Fact(text=entry["text"], remembered_at=entry.get("remembered_at", "")))
    return facts


def remember(text: str, path: "Path | None" = None) -> None:
    """Appends `text` as a new fact, trimming to the `MAX_FACTS` most recent
    if the store has grown past that. Same `None`-default reasoning as
    `load` - see its docstring."""
    path = path if path is not None else DEFAULT_PATH
    facts = load(path)
    facts.append(Fact(text=text, remembered_at=datetime.now(timezone.utc).isoformat()))
    facts = facts[-MAX_FACTS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(f) for f in facts], ensure_ascii=False, indent=2), encoding="utf-8")


def as_context(path: "Path | None" = None) -> "list[str]":
    """Just the fact text, oldest first - the shape `interpret_text` sends
    to Nemotron as context. Timestamps are for humans reading the raw file,
    not useful tokens to spend in every single prompt."""
    return [f.text for f in load(path)]
