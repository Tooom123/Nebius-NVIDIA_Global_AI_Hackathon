"""The file-action perimeter - see `heypeer/executor/safe_zones.py`.

These matter more than most tests here: file actions run with no
confirmation step, so this boundary is what stops a misheard instruction
landing somewhere unrecoverable.
"""

from pathlib import Path

import pytest

from heypeer.executor import safe_zones


def test_the_users_own_files_are_allowed() -> None:
    assert safe_zones.is_allowed(Path.home() / "Documents" / "rapport.pdf")
    assert safe_zones.is_allowed(Path.home() / "Desktop" / "capture.png")
    assert safe_zones.is_allowed(Path.home() / "dev" / "projet" / "main.py")


def test_a_file_that_does_not_exist_yet_is_still_judged() -> None:
    """create_file and create_folder name something that does not exist."""
    assert safe_zones.is_allowed(Path.home() / "Documents" / "pas-encore-la.txt")


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/usr/bin/python",
        "/bin/sh",
        "/boot/vmlinuz",
        "C:/Windows/System32/kernel32.dll",
        "C:/Program Files/app/thing.exe",
        "C:/ProgramData/state.db",
    ],
)
def test_system_locations_are_refused(path: str) -> None:
    assert safe_zones.is_allowed(Path(path)) is False


@pytest.mark.parametrize("sub", [".ssh/id_rsa", ".aws/credentials", ".config/app.conf"])
def test_application_state_inside_home_is_refused(sub: str) -> None:
    """Losing these breaks software rather than losing work, and nobody
    asks a voice assistant to touch them by name."""
    assert safe_zones.is_allowed(Path.home() / sub) is False


def test_a_traversal_out_of_home_is_refused() -> None:
    """The original reason a containment check exists at all."""
    assert safe_zones.is_allowed(Path.home() / ".." / ".." / "etc" / "passwd") is False


def test_a_users_own_folder_named_like_a_system_one_is_not_caught() -> None:
    """"/usr" must not match ~/dev/usr - the check is a path prefix, not a
    substring."""
    assert safe_zones.is_allowed(Path.home() / "dev" / "usr" / "notes.txt")


def test_the_configured_watched_dir_is_allowed_wherever_it_is(tmp_path: Path) -> None:
    """HEYPEER_WATCHED_DIR is explicit user intent; without this, pointing
    it at another drive would silently disable every file action."""
    target = tmp_path / "facture.pdf"
    assert safe_zones.is_allowed(target) is False
    assert safe_zones.is_allowed(target, extra_roots=[tmp_path]) is True


def test_an_extra_root_cannot_unlock_a_system_path() -> None:
    """Pointing the watched directory at C:\\Windows is a mistake, not an
    intention."""
    assert safe_zones.is_allowed(Path("/etc/passwd"), extra_roots=[Path("/etc")]) is False


def test_ensure_allowed_names_what_it_refused() -> None:
    """The message is spoken back, so it has to say where."""
    with pytest.raises(safe_zones.OutsideSafeZone) as excinfo:
        safe_zones.ensure_allowed(Path("/etc/passwd"), "file to delete")
    assert "file to delete" in str(excinfo.value)
    assert "passwd" in str(excinfo.value)


def test_ensure_allowed_returns_the_resolved_path() -> None:
    got = safe_zones.ensure_allowed(Path.home() / "Documents" / ".." / "notes.txt", "file")
    assert got == (Path.home() / "notes.txt").resolve()


def test_search_roots_puts_the_watched_dir_first(tmp_path: Path) -> None:
    """Search order is what disambiguates a name found in two places, so
    nothing that worked before resolves differently now."""
    roots = safe_zones.search_roots(tmp_path)
    assert roots[0] == tmp_path.resolve()


def test_search_roots_without_a_watched_dir_still_works() -> None:
    assert isinstance(safe_zones.search_roots(None), list)


def test_search_roots_has_no_duplicates(tmp_path: Path) -> None:
    roots = safe_zones.search_roots(tmp_path)
    assert len(roots) == len(set(roots))


def test_a_symlinked_config_dir_is_still_refused(tmp_path: Path, monkeypatch) -> None:
    """Regression: ~/.aws as a symlink to another filesystem resolved out of
    home entirely, escaped the app-state check, and was then allowed by the
    other-drive rule. Symlinked dotfiles are completely ordinary."""
    real = tmp_path / "elsewhere" / ".aws"
    real.mkdir(parents=True)
    (real / "credentials").write_text("secret", encoding="utf-8")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    link = fake_home / ".aws"
    link.symlink_to(real)
    monkeypatch.setattr(safe_zones, "home", lambda: fake_home.resolve())
    assert safe_zones.is_allowed(link / "credentials") is False
