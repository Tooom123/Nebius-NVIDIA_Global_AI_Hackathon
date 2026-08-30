"""Tests for the training CLI's directory handling.

Passing four long paths by hand was the most error-prone step of retraining:
on Git Bash a Windows-style `data\\wakeword\\...` silently loses its
backslashes (they are escape characters there), producing a nonsense
directory name that is easy to misread as a missing-files problem.
"""

from pathlib import Path

import pytest

from heypeer.wakeword.train import _default_dirs, _embed_directory


def test_default_dirs_keeps_only_directories_with_clips(tmp_path: Path) -> None:
    with_clips = tmp_path / "positive_user"
    with_clips.mkdir()
    (with_clips / "a.wav").write_bytes(b"x")
    empty = tmp_path / "positive_augmented"
    empty.mkdir()
    missing = tmp_path / "not_there"

    assert _default_dirs([with_clips, empty, missing]) == [with_clips]


def test_default_dirs_is_empty_when_nothing_is_recorded(tmp_path: Path) -> None:
    assert _default_dirs([tmp_path / "nope"]) == []


def test_missing_directory_says_so_and_hints_at_path_separators(tmp_path: Path) -> None:
    """Distinguished from "exists but empty" — the two have completely
    different fixes, and conflating them sent the user hunting for missing
    recordings when the real problem was a mangled path."""
    with pytest.raises(FileNotFoundError) as excinfo:
        _embed_directory(tmp_path / "datawakewordsamplespositive_user", None, None)

    message = str(excinfo.value)
    assert "No such directory" in message
    assert "forward slashes" in message


def test_empty_directory_reports_missing_files_not_a_bad_path(tmp_path: Path) -> None:
    empty = tmp_path / "positive_user"
    empty.mkdir()

    with pytest.raises(FileNotFoundError) as excinfo:
        _embed_directory(empty, None, None)

    assert "No wav files found" in str(excinfo.value)
