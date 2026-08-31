"""Tests for volume, brightness and window control.

Everything that actually touches Windows (`ctypes.windll`, `powershell.exe`)
is guarded behind `sys.platform == "win32"` and unreachable from this Linux
sandbox - what's tested here is that the guard holds (nothing raises, no
Windows-only call is attempted) and, independently, the window-matching
logic itself, which is factored out to take a plain list of windows rather
than calling `EnumWindows` - the same split `apps._find_start_menu_shortcut`
uses for the Start Menu search.
"""

from unittest.mock import patch

import heypeer.executor.system as system


# --- Off-Windows safety -----------------------------------------------------


def test_volume_functions_are_no_ops_off_windows() -> None:
    system.volume_up()
    system.volume_down()
    system.volume_mute_toggle()  # must not raise


def test_window_control_declines_off_windows() -> None:
    assert system.maximize_window("Chrome") is False
    assert system.minimize_window("Chrome") is False
    assert system.close_window("Chrome") is False
    system.minimize_all()  # must not raise


def test_list_windows_is_empty_off_windows() -> None:
    assert system._list_windows() == []


def test_adjust_brightness_reports_failure_off_windows() -> None:
    """False, not a crash and not a silent success - the caller turns this
    into an honest spoken message either way (unsupported hardware on
    Windows looks identical to this from the caller's side)."""
    assert system.adjust_brightness("up") is False


# --- Window-title matching (the testable half) ------------------------------


def test_match_window_finds_a_substring_match() -> None:
    """A real window title is rarely just the bare app name."""
    windows = [(1, "facture.pdf - Google Chrome"), (2, "Discord")]

    assert system._match_window(windows, ["chrome", "google chrome"]) == 1


def test_match_window_matches_case_and_accent_insensitively() -> None:
    windows = [(1, "Paramètres")]

    assert system._match_window(windows, ["parametres"]) == 1


def test_match_window_declines_when_nothing_matches() -> None:
    windows = [(1, "Discord"), (2, "Notepad")]

    assert system._match_window(windows, ["chrome", "google chrome"]) is None


def test_match_window_declines_on_an_empty_window_list() -> None:
    assert system._match_window([], ["chrome"]) is None


def test_resolve_window_declines_for_an_unknown_app() -> None:
    """Goes through the same registry `open_app` does - an app Hey Peer
    does not know can't have a window matched for it either, consistent
    with "ouvre Machin" being refused rather than guessed at."""
    assert system._resolve_window("Machin") is None


def test_resolve_window_uses_the_apps_registry_aliases() -> None:
    with patch("heypeer.executor.system._list_windows",
               return_value=[(42, "facture.pdf - Google Chrome")]):
        assert system._resolve_window("le navigateur") == 42  # Chrome's alias


# --- Volume/brightness call shape (mocked ctypes/subprocess) ---------------


def test_volume_up_presses_the_key_several_times() -> None:
    with patch("sys.platform", "win32"), patch("heypeer.executor.system._press_key") as press:
        system.volume_up()

    assert press.call_count == system.VOLUME_STEP_PRESSES
    assert all(c.args == (system.VK_VOLUME_UP,) for c in press.call_args_list)


def test_volume_mute_presses_the_key_exactly_once() -> None:
    """Mute is a toggle, not a direction - pressing it more than once would
    undo itself."""
    with patch("sys.platform", "win32"), patch("heypeer.executor.system._press_key") as press:
        system.volume_mute_toggle()

    press.assert_called_once_with(system.VK_VOLUME_MUTE)


def test_adjust_brightness_reports_success_when_powershell_answers() -> None:
    with (
        patch("sys.platform", "win32"),
        patch("heypeer.executor.system._run_powershell", return_value="70"),
    ):
        assert system.adjust_brightness("up") is True


def test_adjust_brightness_reports_failure_when_powershell_fails() -> None:
    """No WMI namespace (most external monitors) must degrade to False, not
    an exception reaching the caller."""
    with (
        patch("sys.platform", "win32"),
        patch("heypeer.executor.system._run_powershell", return_value=None),
    ):
        assert system.adjust_brightness("down") is False


def test_run_powershell_returns_none_on_any_failure() -> None:
    with patch("sys.platform", "win32"), patch("subprocess.run", side_effect=OSError("no")):
        assert system._run_powershell("Write-Output 1") is None
