"""Named routines - see `heypeer/executor/routines.py`.

Every test passes an explicit `path` into a tmp_path fixture. The real
store lives in the repo's own `data/`, and a test that wrote there would
both pollute the developer's routines and pass for the wrong reason - a
mistake this project has already made once, in `memory.py`.
"""

from pathlib import Path

from heypeer.executor import routines


def test_a_saved_routine_comes_back(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    routines.remember("routine du matin", ["mets de la musique", "ouvre Slack"], store)
    loaded = routines.load(store)
    assert len(loaded) == 1
    assert loaded[0].name == "routine du matin"
    assert loaded[0].steps == ["mets de la musique", "ouvre Slack"]


def test_no_routines_yet_is_not_an_error(tmp_path: Path) -> None:
    assert routines.load(tmp_path / "nothing.json") == []


def test_a_corrupted_file_degrades_to_empty(tmp_path: Path) -> None:
    """A broken routines file must never block an ordinary turn."""
    store = tmp_path / "routines.json"
    store.write_text("{ not json", encoding="utf-8")
    assert routines.load(store) == []


def test_saving_the_same_name_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    """"en fait ma routine du matin c'est plutot..." is a correction."""
    store = tmp_path / "routines.json"
    routines.remember("matin", ["a"], store)
    routines.remember("matin", ["b", "c"], store)
    loaded = routines.load(store)
    assert len(loaded) == 1
    assert loaded[0].steps == ["b", "c"]


def test_replacing_ignores_case(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    routines.remember("Matin", ["a"], store)
    routines.remember("matin", ["b"], store)
    assert len(routines.load(store)) == 1


def test_a_routine_needs_a_name_and_a_step(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    assert routines.remember("", ["a"], store) is None
    assert routines.remember("matin", [], store) is None
    assert routines.remember("matin", ["   "], store) is None
    assert routines.load(store) == []


def test_steps_are_capped(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    routine = routines.remember("long", [f"step {i}" for i in range(30)], store)
    assert len(routine.steps) == routines.MAX_STEPS


def test_the_store_refuses_to_grow_without_limit(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    for i in range(routines.MAX_ROUTINES):
        assert routines.remember(f"r{i}", ["x"], store) is not None
    assert routines.remember("one too many", ["x"], store) is None


def test_find_matches_loosely(tmp_path: Path) -> None:
    """The user says "lance ma routine du matin" for one stored as "matin"."""
    store = tmp_path / "routines.json"
    routines.remember("matin", ["a"], store)
    assert routines.find("ma routine du matin", store).name == "matin"
    assert routines.find("MATIN", store).name == "matin"


def test_an_exact_match_beats_a_partial_one(tmp_path: Path) -> None:
    """A routine literally called "matin" must not be shadowed by a longer
    name that happens to contain it."""
    store = tmp_path / "routines.json"
    routines.remember("routine du matin tranquille", ["a"], store)
    routines.remember("matin", ["b"], store)
    assert routines.find("matin", store).name == "matin"


def test_find_returns_nothing_for_an_unknown_name(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    routines.remember("matin", ["a"], store)
    assert routines.find("soir", store) is None
    assert routines.find("", store) is None


def test_forget_removes_only_the_named_one(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    routines.remember("matin", ["a"], store)
    routines.remember("soir", ["b"], store)
    assert routines.forget("matin", store).name == "matin"
    assert [r.name for r in routines.load(store)] == ["soir"]


def test_forget_an_unknown_routine_changes_nothing(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    routines.remember("matin", ["a"], store)
    assert routines.forget("soir", store) is None
    assert len(routines.load(store)) == 1


def test_names_returns_names_only(tmp_path: Path) -> None:
    """The bodies stay out of the prompt - that limit is the whole reason
    this doesn't repeat the deleted learned-skills feature's prompt bloat."""
    store = tmp_path / "routines.json"
    routines.remember("matin", ["a very long step " * 20], store)
    assert routines.names(store) == ["matin"]


def test_malformed_entries_are_skipped_not_fatal(tmp_path: Path) -> None:
    store = tmp_path / "routines.json"
    store.write_text(
        '[{"name": "ok", "steps": ["a"]}, {"name": "", "steps": ["b"]}, '
        '{"steps": ["c"]}, "nonsense", {"name": "n", "steps": []}]',
        encoding="utf-8",
    )
    assert [r.name for r in routines.load(store)] == ["ok"]
