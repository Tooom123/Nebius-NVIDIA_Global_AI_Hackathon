"""Shared test fixtures.

The overlay windows (`caption_window`, `countdown_window`) each start a real
`multiprocessing.Process` on construction. In a test run that is pure cost
and a source of flakiness: dozens of forked processes doing nothing, plus a
DeprecationWarning per fork about forking a multi-threaded parent. Nothing
in the suite asserts on a real window - there is no display here - so they
are stubbed out globally rather than patched test by test, where the next
test to speak would silently start forking again.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _no_real_overlay_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces the overlay window classes with mocks for every test."""
    import heypeer.tray.caption_window as caption_window
    import heypeer.tray.countdown_window as countdown_window

    monkeypatch.setattr(caption_window, "CaptionWindow", MagicMock())
    monkeypatch.setattr(countdown_window, "CountdownWindow", MagicMock())
