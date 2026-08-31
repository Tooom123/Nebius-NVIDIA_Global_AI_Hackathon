"""Tests for persistent memory - facts that outlive the exchange they were
told in, unlike `HeyPeer._history` (see `heypeer/memory.py`'s module
docstring for why those are two separate stores).
"""

import json
from pathlib import Path

from heypeer import memory


def test_load_is_empty_for_a_fresh_install(tmp_path: Path) -> None:
    assert memory.load(tmp_path / "memory.json") == []


def test_remember_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"

    memory.remember("Je préfère qu'on m'appelle Tom", path)

    facts = memory.load(path)
    assert len(facts) == 1
    assert facts[0].text == "Je préfère qu'on m'appelle Tom"
    assert facts[0].remembered_at  # a timestamp was recorded


def test_remembering_creates_the_parent_directory(tmp_path: Path) -> None:
    """A fresh install has no data/ directory yet - the first "retiens que"
    must not fail because of that."""
    path = tmp_path / "nested" / "does" / "not" / "exist" / "memory.json"

    memory.remember("un fait", path)

    assert path.is_file()


def test_facts_accumulate_in_order(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"

    memory.remember("premier fait", path)
    memory.remember("deuxieme fait", path)

    facts = memory.load(path)
    assert [f.text for f in facts] == ["premier fait", "deuxieme fait"]


def test_the_store_is_bounded(tmp_path: Path) -> None:
    """A stale fact from months ago must not accumulate forever and bloat
    every single prompt - see the module docstring for why there is no
    "forget this one fact" action yet, which makes this the only thing
    that currently stops the list growing without limit."""
    path = tmp_path / "memory.json"
    for i in range(memory.MAX_FACTS + 10):
        memory.remember(f"fait numero {i}", path)

    facts = memory.load(path)
    assert len(facts) == memory.MAX_FACTS
    # The oldest ones fell off; the most recent survived.
    assert facts[-1].text == f"fait numero {memory.MAX_FACTS + 9}"
    assert facts[0].text == "fait numero 10"


def test_load_degrades_to_empty_on_a_corrupted_file(tmp_path: Path) -> None:
    """A memory failure must never block an ordinary turn - a hand-edited
    or truncated file is the realistic way this happens, not a crash."""
    path = tmp_path / "memory.json"
    path.write_text("not valid json {{{")

    assert memory.load(path) == []


def test_load_degrades_to_empty_when_the_file_is_not_a_list(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text(json.dumps({"not": "a list"}))

    assert memory.load(path) == []


def test_load_skips_malformed_entries_without_failing_the_whole_load(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text(json.dumps([
        {"text": "un vrai fait", "remembered_at": "2026-01-01T00:00:00+00:00"},
        {"not_text": "malformed"},
        "just a string, not an object",
    ]))

    facts = memory.load(path)
    assert [f.text for f in facts] == ["un vrai fait"]


def test_as_context_returns_plain_strings(tmp_path: Path) -> None:
    """The shape `NemotronClient.interpret_text`'s `memory` parameter
    expects - timestamps are for a human reading the raw file, not tokens
    worth spending in every prompt."""
    path = tmp_path / "memory.json"
    memory.remember("Le projet doit être livré vendredi", path)

    assert memory.as_context(path) == ["Le projet doit être livré vendredi"]


def test_as_context_is_empty_for_no_memory(tmp_path: Path) -> None:
    assert memory.as_context(tmp_path / "memory.json") == []
