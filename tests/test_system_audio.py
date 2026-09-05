"""System-audio (loopback) capture - see `heypeer/executor/system_audio.py`.

There is no PyAudioWPatch wheel installable in this sandbox, no audio
device and no Windows, so what is tested here is the logic around the
capture: availability reporting, device selection, and the downmix. Whether
a WASAPI loopback stream actually opens on real hardware is not, and the
module says so.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from heypeer.executor import system_audio


def test_not_available_off_windows() -> None:
    with patch("platform.system", return_value="Linux"):
        assert system_audio.is_available() is False


def test_not_available_without_the_optional_dependency() -> None:
    """An ordinary state on a fresh Windows install, not an error."""
    with patch("platform.system", return_value="Windows"), patch.dict(
        "sys.modules", {"pyaudiowpatch": None}
    ):
        assert system_audio.is_available() is False


def test_capture_refuses_clearly_when_unavailable() -> None:
    with patch.object(system_audio, "is_available", return_value=False):
        with pytest.raises(system_audio.SystemAudioUnavailable):
            system_audio.capture(5)


def test_the_loopback_matching_the_default_output_is_chosen() -> None:
    """A machine with HDMI audio and a headset has several loopback devices;
    capturing the silent one looks like success and returns a minute of
    nothing."""
    pa = MagicMock()
    pa.get_host_api_info_by_type.return_value = {"defaultOutputDevice": 3}
    pa.get_device_info_by_index.return_value = {"name": "Headset (Realtek)"}
    pa.get_loopback_device_info_generator.return_value = iter(
        [
            {"name": "HDMI Output [Loopback]", "index": 8},
            {"name": "Headset (Realtek) [Loopback]", "index": 9},
        ]
    )
    fake_module = MagicMock(paWASAPI=13)
    with patch.dict("sys.modules", {"pyaudiowpatch": fake_module}):
        device = system_audio._default_loopback(pa)
    assert device["index"] == 9


def test_no_matching_loopback_is_an_explicit_failure() -> None:
    """Better a clear error than silently recording the wrong device."""
    pa = MagicMock()
    pa.get_host_api_info_by_type.return_value = {"defaultOutputDevice": 3}
    pa.get_device_info_by_index.return_value = {"name": "Some Device"}
    pa.get_loopback_device_info_generator.return_value = iter([])
    fake_module = MagicMock(paWASAPI=13)
    with patch.dict("sys.modules", {"pyaudiowpatch": fake_module}):
        with pytest.raises(system_audio.SystemAudioUnavailable):
            system_audio._default_loopback(pa)


def test_stereo_is_downmixed_by_averaging_not_by_dropping_a_channel() -> None:
    """Audio panned entirely to one side survives averaging and is lost by
    "just take the left channel"."""
    left_only = np.array([1000, 0, 1000, 0, 1000, 0], dtype=np.int16)
    out = np.frombuffer(
        system_audio._to_mono_16k(left_only, channels=2, rate=system_audio.SAMPLE_RATE),
        dtype=np.int16,
    )
    assert len(out) == 3
    assert all(v == 500 for v in out)


def test_resampling_produces_the_expected_length() -> None:
    audio = np.zeros(48000, dtype=np.int16)
    out = np.frombuffer(
        system_audio._to_mono_16k(audio, channels=1, rate=48000), dtype=np.int16
    )
    assert abs(len(out) - system_audio.SAMPLE_RATE) <= 1


def test_mono_at_the_target_rate_is_passed_through() -> None:
    audio = np.array([1, 2, 3, 4], dtype=np.int16)
    out = np.frombuffer(
        system_audio._to_mono_16k(audio, channels=1, rate=system_audio.SAMPLE_RATE),
        dtype=np.int16,
    )
    assert list(out) == [1, 2, 3, 4]


def test_empty_audio_does_not_crash_the_downmix() -> None:
    out = system_audio._to_mono_16k(np.zeros(0, dtype=np.int16), channels=2, rate=48000)
    assert out == b""


def test_an_odd_number_of_stereo_samples_is_handled() -> None:
    """A capture cut mid-frame must not reshape-crash."""
    audio = np.array([100, 200, 300], dtype=np.int16)  # 1.5 stereo frames
    out = np.frombuffer(
        system_audio._to_mono_16k(audio, channels=2, rate=system_audio.SAMPLE_RATE),
        dtype=np.int16,
    )
    assert len(out) == 1
