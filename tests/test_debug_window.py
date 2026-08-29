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


def test_log_queues_js_with_escaped_text(fake_process: MagicMock) -> None:
    window = _make_window()

    window.log('hello "world"')

    js_call = window._queue.put.call_args.args[0]
    assert js_call.startswith("log(")
    assert '\\"world\\"' in js_call


def test_set_level_clamps_to_0_1(fake_process: MagicMock) -> None:
    window = _make_window()

    window.set_level(1.5)
    assert window._queue.put.call_args.args[0] == "setLevel(1.0)"

    window.set_level(-0.5)
    assert window._queue.put.call_args.args[0] == "setLevel(0.0)"


def test_set_state_queues_js(fake_process: MagicMock) -> None:
    window = _make_window()

    window.set_state("recording")

    assert window._queue.put.call_args.args[0] == 'setState("recording")'


def test_close_sends_none_sentinel(fake_process: MagicMock) -> None:
    window = _make_window()

    window.close()

    assert window._queue.put.call_args.args[0] is None


def test_send_swallows_queue_errors(fake_process: MagicMock) -> None:
    window = _make_window()
    window._queue.put.side_effect = Exception("queue closed")

    window.log("should not raise")  # must not propagate
