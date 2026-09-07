"""First-run colour choice - see `heypeer/tray/onboarding.py`.

Every test passes an explicit path: the real one is the project's own
`.env`, and a test that wrote there would clobber the developer's API key.
This project has already had one test write to a real store by accident
(`memory.py`), which is why that is checked rather than assumed.
"""

from pathlib import Path
from unittest.mock import patch

from heypeer.tray import onboarding
from heypeer.tray.cursor_render import DEFAULT_COLOR


# --- parsing what a person typed ---

def test_hex_with_and_without_a_hash() -> None:
    assert onboarding.parse_color("#ff0000") == (255, 0, 0)
    assert onboarding.parse_color("00c878") == (0, 200, 120)


def test_decimal_triples_are_accepted_too() -> None:
    """The picker gives hex and the env var is decimal; a user copying one
    into the other should not be told they are wrong."""
    assert onboarding.parse_color("255,0,0") == (255, 0, 0)
    assert onboarding.parse_color(" 0 , 200 , 120 ") == (0, 200, 120)


def test_out_of_range_decimals_clamp() -> None:
    assert onboarding.parse_color("300,-20,40") == (255, 0, 40)


def test_nonsense_is_rejected_rather_than_guessed() -> None:
    for bad in ("", "   ", "red", "#zzzzzz", "1,2", "1,2,3,4"):
        assert onboarding.parse_color(bad) is None


# --- persistence ---

def test_a_saved_colour_is_readable_back(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert onboarding.save_color((0, 200, 120), env) is True
    assert "HEYPEER_CURSOR_COLOR=0,200,120" in env.read_text(encoding="utf-8")


def test_saving_preserves_the_rest_of_the_file(tmp_path: Path) -> None:
    """The real .env holds the API key. Losing it would be catastrophic and
    silent."""
    env = tmp_path / ".env"
    env.write_text("NEBIUS_API_KEY=secret\nHEYPEER_WATCHED_DIR=D:/Work\n", encoding="utf-8")
    onboarding.save_color((1, 2, 3), env)
    content = env.read_text(encoding="utf-8")
    assert "NEBIUS_API_KEY=secret" in content
    assert "HEYPEER_WATCHED_DIR=D:/Work" in content


def test_saving_twice_replaces_rather_than_appends(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    onboarding.save_color((1, 1, 1), env)
    onboarding.save_color((2, 2, 2), env)
    lines = [ln for ln in env.read_text(encoding="utf-8").splitlines() if "CURSOR_COLOR" in ln]
    assert lines == ["HEYPEER_CURSOR_COLOR=2,2,2"]


def test_rewriting_does_not_accumulate_blank_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\n\n\n", encoding="utf-8")
    onboarding.save_color((1, 1, 1), env)
    onboarding.save_color((2, 2, 2), env)
    assert "\n\n\n" not in env.read_text(encoding="utf-8")


def test_an_unwritable_file_is_reported_not_raised(tmp_path: Path) -> None:
    with patch("pathlib.Path.write_text", side_effect=OSError("read-only")):
        assert onboarding.save_color((1, 2, 3), tmp_path / ".env") is False


# --- asking once ---

def test_a_fresh_install_has_not_been_asked(tmp_path: Path) -> None:
    assert onboarding.has_been_asked(tmp_path / "nothing.env") is False


def test_a_saved_choice_counts_as_asked(tmp_path: Path) -> None:
    """Reads the file rather than the environment - this has to be true
    immediately after writing, before any restart."""
    env = tmp_path / ".env"
    onboarding.save_color((1, 2, 3), env)
    assert onboarding.has_been_asked(env) is True


def test_an_unrelated_env_file_does_not_count_as_asked(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("NEBIUS_API_KEY=secret\n", encoding="utf-8")
    assert onboarding.has_been_asked(env) is False


# --- the whole step ---

def test_it_does_not_ask_twice(tmp_path: Path) -> None:
    """A first run that opens a dialog is onboarding; a second one is an
    annoyance."""
    env = tmp_path / ".env"
    onboarding.save_color((9, 9, 9), env)
    with patch.object(onboarding, "env_path", return_value=env), patch.object(
        onboarding, "ask_cursor_color"
    ) as ask:
        onboarding.run_if_needed(log=lambda _m: None)
    ask.assert_not_called()


def test_cancelling_is_recorded_so_it_stops_asking(tmp_path: Path) -> None:
    """Cancelling means "the default is fine", not "ask me again tomorrow"."""
    env = tmp_path / ".env"
    with patch.object(onboarding, "env_path", return_value=env), patch.object(
        onboarding, "ask_cursor_color", return_value=None
    ):
        assert onboarding.run_if_needed(log=lambda _m: None) == DEFAULT_COLOR
    assert onboarding.has_been_asked(env) is True


def test_a_chosen_colour_is_returned_and_saved(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    with patch.object(onboarding, "env_path", return_value=env), patch.object(
        onboarding, "ask_cursor_color", return_value=(10, 20, 30)
    ):
        assert onboarding.run_if_needed(log=lambda _m: None) == (10, 20, 30)
    assert "10,20,30" in env.read_text(encoding="utf-8")


def test_no_display_falls_back_to_the_default(tmp_path: Path) -> None:
    """A headless machine must still start."""
    env = tmp_path / ".env"
    with patch.object(onboarding, "env_path", return_value=env), patch.object(
        onboarding, "ask_cursor_color", side_effect=RuntimeError("no display")
    ):
        assert onboarding.run_if_needed(log=lambda _m: None) == DEFAULT_COLOR
