"""The blob preview renderer - see `heypeer/tray/blob_preview.py`.

A dev tool, so the bar is "does it produce the right frames and fail
clearly", not the full treatment. The one thing worth guarding hard is that
it keeps taking its parameters from the live indicator rather than growing
its own copy - a preview that has drifted from the thing it previews is
worse than none.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from heypeer.tray import blob_preview


def test_it_renders_the_requested_number_of_frames() -> None:
    got = list(blob_preview.frames("idle", seconds=0.2, size=64))
    assert len(got) == int(0.2 * blob_preview.FPS)
    assert got[0].size == (64, 64)


def test_every_live_state_can_be_rendered() -> None:
    """Guards against a state being added to the indicator and this tool
    silently not covering it."""
    from heypeer.tray.debug_window import STATE_ENERGY

    for state in STATE_ENERGY:
        assert list(blob_preview.frames(state, seconds=0.1, size=48))


def test_an_unknown_state_fails_clearly() -> None:
    with pytest.raises(SystemExit) as excinfo:
        list(blob_preview.frames("nonsense", seconds=0.1, size=48))
    assert "nonsense" in str(excinfo.value)


def test_a_reactive_state_actually_reacts_to_the_level() -> None:
    """`speaking` has a non-zero level_gain, so pinning the mic level low
    and high must not produce identical frames."""
    quiet = list(blob_preview.frames("speaking", 0.1, 48, level=0.0))
    loud = list(blob_preview.frames("speaking", 0.1, 48, level=1.0))
    assert quiet[0].tobytes() != loud[0].tobytes()


def test_the_simulated_level_stays_in_range() -> None:
    """It feeds gains that assume 0..1; out of range would distort the
    preview relative to the real thing."""
    for i in range(200):
        assert 0.0 <= blob_preview._simulated_level(i / 30) <= 1.0


def test_it_falls_back_to_a_gif_without_ffmpeg(tmp_path: Path) -> None:
    """Never hard-depend on a binary the user may not have."""
    images = list(blob_preview.frames("idle", 0.1, 48))
    with patch("shutil.which", return_value=None):
        written = blob_preview.write_video(images, tmp_path / "out.mp4")
    assert written.suffix == ".gif"
    assert written.is_file()


def test_writing_nothing_is_an_error_not_an_empty_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        blob_preview.write_video([], tmp_path / "out.mp4")


def test_the_cli_rejects_an_unknown_state() -> None:
    with pytest.raises(SystemExit):
        blob_preview.main(["--state", "nonsense"])
