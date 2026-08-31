"""Tests for clipboard read/write and the simulated Ctrl+C.

`copy_selection` (a `keybd_event` call) is Windows-only and unreachable from
this Linux sandbox, same as `executor/system.py`'s volume/window control.
`read`/`write` go through `pyperclip`, which is mocked here for determinism
- this sandbox happens to have a working clipboard backend, but a CI runner
or a headless box is not guaranteed to, and the point of these tests is
this module's own logic (does a read failure degrade to None, not an
exception), not pyperclip's own correctness.
"""

from unittest.mock import MagicMock, patch

import heypeer.executor.clipboard as clipboard


def test_copy_selection_is_a_no_op_off_windows() -> None:
    clipboard.copy_selection()  # must not raise


def test_copy_selection_sends_ctrl_c_on_windows() -> None:
    with patch("sys.platform", "win32"), patch("ctypes.windll", create=True) as windll:
        clipboard.copy_selection()

    calls = [c.args for c in windll.user32.keybd_event.call_args_list]
    assert calls == [
        (clipboard._VK_CONTROL, 0, 0, 0),
        (clipboard._VK_C, 0, 0, 0),
        (clipboard._VK_C, 0, clipboard._KEYEVENTF_KEYUP, 0),
        (clipboard._VK_CONTROL, 0, clipboard._KEYEVENTF_KEYUP, 0),
    ]


def test_read_returns_the_clipboard_text() -> None:
    with patch("pyperclip.paste", return_value="facture.pdf"):
        assert clipboard.read() == "facture.pdf"


def test_read_returns_none_for_an_empty_clipboard() -> None:
    with patch("pyperclip.paste", return_value=""):
        assert clipboard.read() is None


def test_read_degrades_to_none_rather_than_raising() -> None:
    """An image, a file list, or a locked clipboard on someone else's
    machine must not surface as an unhandled exception mid-turn."""
    with patch("pyperclip.paste", side_effect=Exception("not text")):
        assert clipboard.read() is None


def test_write_goes_through_pyperclip() -> None:
    with patch("pyperclip.copy") as copy_mock:
        clipboard.write("hello")

    copy_mock.assert_called_once_with("hello")
