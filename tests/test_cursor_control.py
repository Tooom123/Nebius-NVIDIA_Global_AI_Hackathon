"""Delivering a click - see `heypeer/executor/cursor_control.py`.

No Windows here, so `ctypes.windll` is mocked. What that can honestly test
is the coordinate arithmetic (pure, and the part whose wrongness would show
up as clicking near-but-not-on a target), the call sequence, and the
refusal everywhere else. Whether a real button depresses is for the manual
test plan.
"""

from unittest.mock import MagicMock, patch

import pytest

from heypeer.executor import cursor_control as cc


def test_not_supported_off_windows() -> None:
    with patch("platform.system", return_value="Linux"):
        assert cc.is_supported() is False
        with pytest.raises(cc.ClickUnavailable):
            cc.click_at(10, 10)


# --- coordinate mapping ---

def test_a_pixel_maps_into_the_absolute_range() -> None:
    """SendInput's absolute space is 0..65535 per axis, not pixels."""
    assert cc.to_absolute(0, 0, (0, 0, 1920, 1080)) == (0, 0)
    assert cc.to_absolute(1920, 1080, (0, 0, 1920, 1080)) == (cc.ABSOLUTE_RANGE, cc.ABSOLUTE_RANGE)


def test_the_centre_of_the_screen_maps_to_the_middle() -> None:
    ax, ay = cc.to_absolute(960, 540, (0, 0, 1920, 1080))
    assert abs(ax - cc.ABSOLUTE_RANGE // 2) < 40
    assert abs(ay - cc.ABSOLUTE_RANGE // 2) < 40


def test_a_monitor_left_of_the_primary_one_still_maps() -> None:
    """A second screen to the left gives negative pixel coordinates, which
    must still land inside 0..65535 rather than clamping to the corner."""
    screen = (-1920, 0, 3840, 1080)  # two 1920 monitors, primary on the right
    ax, _ = cc.to_absolute(-960, 540, screen)
    assert 0 < ax < cc.ABSOLUTE_RANGE // 2


def test_out_of_range_coordinates_clamp_rather_than_wrap() -> None:
    """A resolved element partly offscreen must not click at the opposite
    edge, which is what an unclamped negative would do."""
    assert cc.to_absolute(-5000, -5000, (0, 0, 1920, 1080)) == (0, 0)
    assert cc.to_absolute(99999, 99999, (0, 0, 1920, 1080)) == (
        cc.ABSOLUTE_RANGE,
        cc.ABSOLUTE_RANGE,
    )


def test_a_zero_sized_screen_does_not_divide_by_zero() -> None:
    """GetSystemMetrics can return 0 while a display is being reconfigured."""
    assert cc.to_absolute(10, 10, (0, 0, 0, 0)) == (cc.ABSOLUTE_RANGE, cc.ABSOLUTE_RANGE)


# --- the click sequence ---

def _fake_windll(monkeypatch, cursor_at=(500, 500)):
    user32 = MagicMock()
    user32.SendInput.return_value = 1
    user32.GetSystemMetrics.side_effect = lambda m: {
        cc.SM_XVIRTUALSCREEN: 0, cc.SM_YVIRTUALSCREEN: 0,
        cc.SM_CXVIRTUALSCREEN: 1920, cc.SM_CYVIRTUALSCREEN: 1080,
    }[m]

    def get_cursor_pos(ref):
        ref._obj.x, ref._obj.y = cursor_at
        return 1

    user32.GetCursorPos.side_effect = get_cursor_pos
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(cc.ctypes, "windll", MagicMock(user32=user32), raising=False)
    monkeypatch.setattr(cc.time, "sleep", lambda _s: None)
    return user32


def test_a_click_moves_presses_and_releases(monkeypatch) -> None:
    user32 = _fake_windll(monkeypatch)
    cc.click_at(100, 200, restore=False)
    assert user32.SendInput.call_count == 3, "move, down, up"


def test_the_users_pointer_is_given_back(monkeypatch) -> None:
    """They were in the middle of something. An assistant that leaves the
    mouse somewhere else after every action is worse than one that cannot
    click at all."""
    user32 = _fake_windll(monkeypatch)
    cc.click_at(100, 200)
    assert user32.SendInput.call_count == 4, "move, down, up, move back"


def test_a_right_click_uses_the_right_button(monkeypatch) -> None:
    _fake_windll(monkeypatch)
    with patch.object(cc, "_send") as send:
        cc.click_at(10, 10, button="right", restore=False)
    flags = [call.args[0] for call in send.call_args_list]
    assert cc.MOUSEEVENTF_RIGHTDOWN in flags
    assert cc.MOUSEEVENTF_LEFTDOWN not in flags


def test_the_press_is_held_briefly(monkeypatch) -> None:
    """Zero hold works on most controls and fails on the ones that
    distinguish a click from a glitch."""
    _fake_windll(monkeypatch)
    slept = []
    monkeypatch.setattr(cc.time, "sleep", slept.append)
    cc.click_at(10, 10, restore=False)
    assert slept == [cc.CLICK_HOLD_SECONDS]


def test_a_refused_send_raises_rather_than_reporting_success(monkeypatch) -> None:
    """SendInput returning 0 means the event was blocked - by UIPI, by
    another app's low-level hook. Silently continuing would tell the user
    a click happened when none did."""
    user32 = _fake_windll(monkeypatch)
    user32.SendInput.return_value = 0
    with pytest.raises(cc.ClickUnavailable):
        cc.click_at(10, 10, restore=False)


def test_move_to_does_not_press_anything(monkeypatch) -> None:
    _fake_windll(monkeypatch)
    with patch.object(cc, "_send") as send:
        cc.move_to(50, 60)
    assert send.call_count == 1
    assert send.call_args.args[0] & cc.MOUSEEVENTF_MOVE
