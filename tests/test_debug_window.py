from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_process(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The real window lives in a child process (see debug_window.py's module
    docstring: a thread-based version could hang the whole interpreter in
    this project's Linux sandbox). Constructing a real child process here
    would still try to import/init pywebview for real, so `Process` itself
    is stubbed — these tests only cover `DebugWindow`'s own logic (the JS it
    queues), not pywebview's rendering, same as every other real-GUI
    dependency in this project."""
    import heypeer.tray.debug_window as debug_window

    fake_process_cls = MagicMock()
    fake_process_instance = MagicMock()
    fake_process_cls.return_value = fake_process_instance
    monkeypatch.setattr(debug_window.multiprocessing, "Process", fake_process_cls)
    monkeypatch.setattr(debug_window.multiprocessing, "Queue", MagicMock)
    return fake_process_instance


def _make_window():
    from heypeer.tray.debug_window import DebugWindow

    return DebugWindow()


def test_init_starts_a_daemon_process(fake_process: MagicMock) -> None:
    window = _make_window()

    window._process.start.assert_called_once()


def test_set_level_clamps_to_0_1(fake_process: MagicMock) -> None:
    window = _make_window()

    window.set_level(1.5)
    assert window._queue.put.call_args.args[0] == ("level", 1.0)

    window.set_level(-0.5)
    assert window._queue.put.call_args.args[0] == ("level", 0.0)


def test_set_state_forwards_the_state(fake_process: MagicMock) -> None:
    window = _make_window()

    window.set_state("recording")

    assert window._queue.put.call_args.args[0] == ("state", "recording")


def test_set_state_is_deduplicated(fake_process: MagicMock) -> None:
    """Called from the audio callback on every chunk (~12x/second); an
    unchanged state must not queue another window transition."""
    window = _make_window()

    window.set_state("recording")
    window._queue.reset_mock()
    window.set_state("recording")

    window._queue.put.assert_not_called()


def test_close_sends_quit(fake_process: MagicMock) -> None:
    window = _make_window()

    window.close()

    assert window._queue.put.call_args.args[0] == ("quit", None)


def test_visible_states_cover_an_open_exchange() -> None:
    """The indicator appears when Hey Peer has heard something and stays for
    as long as the exchange is open - including while a question it asked is
    still waiting for an answer, which used to slide it off screen mid-
    conversation. It is hidden while merely listening for a wake word."""
    from heypeer.tray.debug_window import _VISIBLE_STATES

    assert {"recording", "thinking", "speaking", "awaiting"} == _VISIBLE_STATES
    assert "listening" not in _VISIBLE_STATES
    assert "idle" not in _VISIBLE_STATES


def test_send_swallows_queue_errors(fake_process: MagicMock) -> None:
    window = _make_window()
    window._queue.put.side_effect = Exception("queue closed")

    window.set_state("should not raise")  # must not propagate
