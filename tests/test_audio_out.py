"""Playback interruption - see `heypeer/tray/audio_out.py`.

These drive the real `play`/`stop` against a fake PyAudio, because what is
being tested is precisely the chunking loop those functions run: a test that
mocked `play` itself would assert nothing about whether an utterance can
actually be cut short.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from heypeer.tray import audio_out


@pytest.fixture(autouse=True)
def _reset_stop_flag():
    """Every test starts with nothing asking playback to stop."""
    audio_out._stop.clear()
    yield
    audio_out._stop.clear()


def _fake_pyaudio() -> MagicMock:
    pa = MagicMock()
    pa.get_format_from_width.return_value = 8
    return pa


def test_play_writes_everything_when_uninterrupted() -> None:
    pa = _fake_pyaudio()
    samples = b"\x00\x01" * 4096
    with patch.object(audio_out, "_instance", return_value=pa):
        assert audio_out.play(samples, rate=22050) is True
    written = b"".join(call.args[0] for call in pa.open.return_value.write.call_args_list)
    assert written == samples


def test_play_sends_audio_in_chunks_not_one_blocking_write() -> None:
    """The whole point: a single `stream.write(samples)` has nowhere to
    notice that the user wants to interrupt."""
    pa = _fake_pyaudio()
    samples = b"\x00\x01" * 4096
    with patch.object(audio_out, "_instance", return_value=pa):
        audio_out.play(samples, rate=22050)
    assert pa.open.return_value.write.call_count > 1


def test_stop_cuts_playback_short() -> None:
    pa = _fake_pyaudio()
    stream = pa.open.return_value

    # Ask it to stop once the first chunk has gone out.
    def stop_after_first_write(_data):
        audio_out.stop()

    stream.write.side_effect = stop_after_first_write
    samples = b"\x00\x01" * 4096
    with patch.object(audio_out, "_instance", return_value=pa):
        assert audio_out.play(samples, rate=22050) is False
    written = b"".join(call.args[0] for call in stream.write.call_args_list)
    assert len(written) < len(samples)


def test_stream_is_closed_even_when_stopped() -> None:
    """A cut-short utterance must not leak the output stream."""
    pa = _fake_pyaudio()
    stream = pa.open.return_value
    stream.write.side_effect = lambda _data: audio_out.stop()
    with patch.object(audio_out, "_instance", return_value=pa):
        audio_out.play(b"\x00\x01" * 4096, rate=22050)
    stream.stop_stream.assert_called_once()
    stream.close.assert_called_once()


def test_a_stale_stop_does_not_cancel_the_next_utterance() -> None:
    """`stop` called when nothing is playing (or after playback already
    finished) must not silently swallow whatever is said next."""
    audio_out.stop()  # nothing playing
    pa = _fake_pyaudio()
    samples = b"\x00\x01" * 4096
    with patch.object(audio_out, "_instance", return_value=pa):
        assert audio_out.play(samples, rate=22050) is True


def test_stop_is_safe_with_no_playback_in_flight() -> None:
    audio_out.stop()
    audio_out.stop()
