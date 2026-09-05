"""Run-at-login - see `heypeer/startup.py`.

No Windows here, so what is testable is the command the shortcut would
carry and the honest refusal everywhere else.
"""

import sys
from pathlib import Path

import pytest

from heypeer import startup


def test_not_supported_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert startup.is_supported() is False
    with pytest.raises(startup.StartupUnavailable):
        startup.enable()


def test_a_checkout_launches_the_current_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The system python will not have this project's dependencies; the
    virtualenv's one, which is sys.executable, will."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target, arguments, workdir = startup.launch_command()
    assert target == sys.executable
    assert "heypeer.main" in arguments
    assert (Path(workdir) / "heypeer").is_dir()


def test_a_frozen_build_launches_itself(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "HeyPeer.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    target, arguments, workdir = startup.launch_command()
    assert target == str(exe)
    assert arguments == ""
    assert workdir == str(tmp_path)


def test_status_reports_off_when_there_is_no_shortcut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(startup, "shortcut_path", lambda: tmp_path / "Hey Peer.lnk")
    assert startup.is_enabled() is False


def test_status_reports_on_when_the_shortcut_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    link = tmp_path / "Hey Peer.lnk"
    link.write_text("", encoding="utf-8")
    monkeypatch.setattr(startup, "shortcut_path", lambda: link)
    assert startup.is_enabled() is True


def test_disable_distinguishes_removed_from_already_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    link = tmp_path / "Hey Peer.lnk"
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(startup, "shortcut_path", lambda: link)
    assert startup.disable() is False
    link.write_text("", encoding="utf-8")
    assert startup.disable() is True
    assert not link.exists()


def test_the_cli_reports_rather_than_crashing_off_windows(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert startup.main(["enable"]) == 1
    assert "Cannot manage login startup" in capsys.readouterr().err
