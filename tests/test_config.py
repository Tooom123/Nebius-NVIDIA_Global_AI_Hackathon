from pathlib import Path

import pytest

from heypeer.config import load_settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "NEBIUS_API_KEY",
        "NEBIUS_BASE_URL",
        "NEMOTRON_MODEL_ID",
        "HEYPEER_WATCHED_DIR",
        "HEYPEER_WAKEWORD_DEBUG",
        "HEYPEER_WAKEWORD_THRESHOLD",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_empty_string_env_vars_fall_back_to_defaults(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: a blank line in .env (KEY=) sets the env var to an
    empty string, not "unset" — os.environ.get(key, default) returns "" in
    that case, not the default. This has broken HEYPEER_WATCHED_DIR before;
    guards every env var that isn't meant to accept an empty string."""
    monkeypatch.setenv("HEYPEER_WATCHED_DIR", "")
    monkeypatch.setenv("HEYPEER_WAKEWORD_THRESHOLD", "")
    monkeypatch.setenv("HEYPEER_WAKEWORD_DEBUG", "")

    settings = load_settings()  # must not raise

    assert settings.watched_dir == Path.home() / "Downloads"
    assert settings.wakeword_threshold == 0.9
    assert settings.wakeword_debug is False


def test_explicit_env_vars_are_respected(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEYPEER_WATCHED_DIR", "/tmp/somewhere")
    monkeypatch.setenv("HEYPEER_WAKEWORD_THRESHOLD", "0.75")
    monkeypatch.setenv("HEYPEER_WAKEWORD_DEBUG", "1")

    settings = load_settings()

    assert settings.watched_dir == Path("/tmp/somewhere")
    assert settings.wakeword_threshold == 0.75
    assert settings.wakeword_debug is True
