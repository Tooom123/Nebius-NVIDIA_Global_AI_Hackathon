"""Tests for the screenshot capture behind "read_screen".

This Linux sandbox has no real display `PIL.ImageGrab` can capture from -
confirmed directly (`ImageGrab.grab()` raises `OSError: X get_image failed`
here), which is exactly the failure path `capture()` exists to degrade
from. What's tested is that degradation, and the resize logic, not the
capture call itself.
"""

from unittest.mock import MagicMock, patch

from PIL import Image

from heypeer.executor.screen import MAX_WIDTH, capture


def test_capture_returns_none_when_grabbing_fails() -> None:
    """The real failure mode on this sandbox, confirmed directly: no
    display for PIL.ImageGrab to capture from. Any environment without one
    (a headless CI runner, this dev sandbox) must degrade the same way."""
    assert capture() is None


def test_capture_returns_none_rather_than_raising_for_any_grab_failure() -> None:
    with patch("PIL.ImageGrab.grab", side_effect=OSError("no display")):
        assert capture() is None


def test_capture_returns_png_bytes() -> None:
    fake_screenshot = Image.new("RGB", (100, 60), (10, 20, 30))
    with patch("PIL.ImageGrab.grab", return_value=fake_screenshot):
        result = capture()

    assert result is not None
    assert result[:8] == b"\x89PNG\r\n\x1a\n"  # the PNG file signature


def test_capture_resizes_a_wide_screenshot() -> None:
    fake_screenshot = Image.new("RGB", (3840, 2160), (0, 0, 0))  # 4K
    with patch("PIL.ImageGrab.grab", return_value=fake_screenshot):
        result = capture()

    import io

    resized = Image.open(io.BytesIO(result))
    assert resized.width == MAX_WIDTH
    # Aspect ratio preserved.
    assert abs(resized.height / resized.width - 2160 / 3840) < 0.01


def test_capture_does_not_resize_a_screenshot_already_narrow_enough() -> None:
    fake_screenshot = Image.new("RGB", (800, 600), (0, 0, 0))
    with patch("PIL.ImageGrab.grab", return_value=fake_screenshot):
        result = capture()

    import io

    image = Image.open(io.BytesIO(result))
    assert image.width == 800


def test_capture_handles_a_screenshot_with_an_alpha_channel() -> None:
    """PNG's own screenshots can come back RGBA; PNG output must not fail
    trying to encode a mode it wasn't given."""
    fake_screenshot = Image.new("RGBA", (100, 60), (10, 20, 30, 255))
    with patch("PIL.ImageGrab.grab", return_value=fake_screenshot):
        result = capture()

    assert result is not None
