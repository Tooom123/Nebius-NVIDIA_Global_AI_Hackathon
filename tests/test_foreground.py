"""Raising a window, against a user32 that records the calls it gets."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from heypeer.executor import foreground


def _windll(foreground_thread: int = 7, our_thread: int = 3):
    user32 = MagicMock()
    user32.GetWindowThreadProcessId.return_value = foreground_thread
    user32.AttachThreadInput.return_value = 1
    kernel32 = MagicMock()
    kernel32.GetCurrentThreadId.return_value = our_thread
    return SimpleNamespace(user32=user32, kernel32=kernel32)


def _raise(windll, **kwargs) -> None:
    with patch.object(foreground.ctypes, "windll", windll, create=True), \
            patch("heypeer.executor.foreground.time.sleep"):
        foreground.raise_window(42, **kwargs)


def test_a_minimised_window_is_restored_first() -> None:
    windll = _windll()
    _raise(windll)
    assert windll.user32.ShowWindow.call_args_list[0].args == (42, foreground.SW_RESTORE)


def test_it_goes_topmost_and_straight_back() -> None:
    """Above everything for an instant, without staying pinned there."""
    windll = _windll()
    _raise(windll)
    inserts = [c.args[1] for c in windll.user32.SetWindowPos.call_args_list]
    assert inserts == [foreground.HWND_TOPMOST, foreground.HWND_NOTOPMOST]


def test_a_stage_moves_the_window_onto_that_screen() -> None:
    windll = _windll()
    _raise(windll, stage=(1920, 0, 1920, 1080), maximize=False)
    first = windll.user32.SetWindowPos.call_args_list[0].args
    assert first[2:6] == (1920, 0, 1920, 1080)
    assert (42, foreground.SW_MAXIMIZE) not in [c.args for c in windll.user32.ShowWindow.call_args_list]


def test_input_is_attached_and_always_detached() -> None:
    windll = _windll()
    windll.user32.SetForegroundWindow.side_effect = OSError("refused")
    try:
        _raise(windll)
    except OSError:
        pass
    attach = [c.args for c in windll.user32.AttachThreadInput.call_args_list]
    assert attach == [(3, 7, True), (3, 7, False)]


def test_no_attach_when_we_already_own_the_foreground() -> None:
    windll = _windll(foreground_thread=3, our_thread=3)
    _raise(windll)
    windll.user32.AttachThreadInput.assert_not_called()
    windll.user32.SetForegroundWindow.assert_called_once_with(42)
