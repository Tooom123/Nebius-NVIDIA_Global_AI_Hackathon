import ctypes
import struct
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from heypeer.tray.cursor import (
    OCR_NORMAL,
    SPI_SETCURSORS,
    CursorIndicator,
    _write_cur_file,
)


def test_write_cur_file_has_valid_header(tmp_path: Path) -> None:
    image = Image.new("RGBA", (16, 16), (0, 255, 0, 255))
    out_path = tmp_path / "cursor.cur"
    _write_cur_file(image, hotspot=(1, 2), out_path=out_path)

    data = out_path.read_bytes()
    reserved, cur_type, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0
    assert cur_type == 2  # cursor, not icon
    assert count == 1

    width, height, color_count, res, hot_x, hot_y, size, offset = struct.unpack(
        "<BBBBHHII", data[6:22]
    )
    assert (width, height) == (16, 16)
    assert (hot_x, hot_y) == (1, 2)
    assert offset == 22
    assert len(data) == 22 + size


def test_set_active_noop_on_non_windows(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("heypeer.tray.cursor.platform.system", lambda: "Linux")
    indicator = CursorIndicator()

    indicator.set_active(True)

    assert "non supporté" in capsys.readouterr().out


def test_set_active_is_idempotent_for_same_value(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("heypeer.tray.cursor.platform.system", lambda: "Linux")
    indicator = CursorIndicator()

    indicator.set_active(True)
    capsys.readouterr()  # clear the first message
    indicator.set_active(True)

    assert capsys.readouterr().out == ""


def test_set_active_windows_calls_set_system_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("heypeer.tray.cursor.platform.system", lambda: "Windows")
    # The real bitmap extraction (GetIconInfo/GetDIBits) can only be verified
    # on real Windows — here we only check that _apply_windows wires its
    # result into SetSystemCursor correctly.
    monkeypatch.setattr(
        "heypeer.tray.cursor._extract_recolored_arrow",
        lambda tint: (Image.new("RGBA", (4, 4), tint), (0, 0)),
    )
    fake_user32 = MagicMock()
    fake_user32.LoadCursorFromFileW.return_value = 12345
    fake_windll = MagicMock(user32=fake_user32)
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)

    indicator = CursorIndicator()
    indicator.set_active(True)

    fake_user32.LoadCursorFromFileW.assert_called_once()
    fake_user32.SetSystemCursor.assert_called_once_with(12345, OCR_NORMAL)

    indicator.set_active(False)
    fake_user32.SystemParametersInfoW.assert_called_once_with(SPI_SETCURSORS, 0, None, 0)


def test_reset_always_resets_even_if_never_toggled_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards the bug where quitting after a crash-recovered/fresh instance
    silently skipped the reset because `_active` was already False."""
    monkeypatch.setattr("heypeer.tray.cursor.platform.system", lambda: "Windows")
    fake_user32 = MagicMock()
    fake_windll = MagicMock(user32=fake_user32)
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)

    indicator = CursorIndicator()
    indicator.reset()  # never called set_active(True) first

    fake_user32.SystemParametersInfoW.assert_called_once_with(SPI_SETCURSORS, 0, None, 0)
