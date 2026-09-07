"""Tests for the screenshot capture behind "read_screen".

Nothing here calls `PIL.ImageGrab` for real. Whether a grab succeeds
depends entirely on the machine - it fails in a bare sandbox and succeeds
under `xvfb-run` on CI - so a test that relied on either outcome would be
testing the environment rather than the code. What is tested is the
degradation path and the resize logic, both driven by patching the grab.
"""

from unittest.mock import MagicMock, patch

from PIL import Image

from heypeer.executor.screen import MAX_WIDTH, capture


def test_capture_returns_none_rather_than_raising_for_any_grab_failure() -> None:
    """Degradation is the property that matters, and this is the honest way
    to test it.

    There used to be a second test above this one that simply called
    `capture()` and asserted None, on the reasoning that this sandbox has no
    display. That passed for an environmental reason rather than a
    behavioural one, and CI proved it: under `xvfb-run` there *is* a
    display, the grab succeeds, and the assertion failed on a machine where
    nothing was wrong. Patching the failure is what actually pins the
    behaviour, on any machine.
    """
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
