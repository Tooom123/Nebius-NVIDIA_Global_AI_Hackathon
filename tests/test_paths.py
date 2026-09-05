"""Path resolution across checkout and frozen builds - see `heypeer/paths.py`.

The distinction under test is the one a frozen build gets wrong silently:
user data written into PyInstaller's unpack directory appears to save and
is gone on the next launch, with nothing raising.
"""

import sys
from pathlib import Path

import pytest

from heypeer import paths


def test_from_a_checkout_nothing_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing layout must keep working: data/ beside the source is
    what the tests, the training scripts and the developer already use."""
    monkeypatch.delenv("HEYPEER_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    assert paths.data_root().name == "data"
    assert paths.resource_root() == Path(paths.__file__).resolve().parent.parent


def test_a_frozen_build_reads_resources_from_the_unpack_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.resource_root() == tmp_path


def test_a_frozen_build_does_not_write_user_data_into_the_unpack_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bug this module exists to prevent: that directory is deleted when
    the process exits, so saving there loses everything on every restart."""
    monkeypatch.delenv("HEYPEER_DATA_DIR", raising=False)
    unpack_dir = tmp_path / "meipass"       # PyInstaller's temp dir
    appdata_dir = tmp_path / "localappdata"  # a genuinely separate location
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(unpack_dir), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata_dir))
    monkeypatch.setattr(sys, "platform", "win32")

    root = paths.data_root()
    assert root != unpack_dir
    assert unpack_dir not in root.parents, "user data would be lost on restart"
    assert appdata_dir in root.parents or root == appdata_dir


def test_the_environment_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEYPEER_DATA_DIR", str(tmp_path / "elsewhere"))
    assert paths.data_root() == tmp_path / "elsewhere"


def test_helpers_join_under_the_right_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEYPEER_DATA_DIR", str(tmp_path))
    assert paths.user_data("memory.json") == tmp_path / "memory.json"
    assert paths.resource("heypeer", "assets") == paths.resource_root() / "heypeer" / "assets"


def test_the_bundled_chime_actually_resolves() -> None:
    """Guards the resource/user-data classification: the chime ships with
    the app, so it must resolve under resource_root and exist."""
    from heypeer.wakeword.listener import CHIME_PATH

    assert CHIME_PATH.is_file()
