"""Capturing what the computer is *playing*, not what the microphone hears.

"resume ce que dit cette video", "qu'est-ce qu'il vient de dire ?" - the
machine already has that audio; the microphone is the wrong way to get it,
picking up the room, the fan and a compressed re-recording of speech that
exists losslessly a layer below.

## Why this is Windows-only and optional

Loopback recording is a WASAPI feature, and the `pyaudio` build this
project already depends on does not expose it. `PyAudioWPatch` is the same
library with WASAPI loopback added, and it publishes Windows wheels only -
there is no Linux build to install even for testing, which is also a fair
description of the feature itself.

So it is an optional dependency, not a required one: `is_available()`
reports honestly, everything degrades to saying so, and the rest of Hey
Peer neither knows nor cares. The same shape as `coding_agent.py` and
`general_agent.py` - a capability that may or may not be present on the
machine, never an import that can break startup.

## What is verified from this sandbox, and what is not

Not much, and it is worth being exact rather than implying otherwise. There
is no `PyAudioWPatch` wheel installable here, no audio device, and no
Windows. The device-selection logic and the buffering are unit-tested
against a fake, the availability check is real, and whether a WASAPI
loopback stream actually opens on the user's hardware is unproven.
"""

import platform

# A minute is enough for "what did they just say" and bounded enough that a
# forgotten capture cannot eat memory. At 16kHz mono int16 this is ~2MB.
MAX_CAPTURE_SECONDS = 60.0
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1024


class SystemAudioUnavailable(RuntimeError):
    """No loopback capture on this machine - not Windows, or the optional
    dependency is missing, or no output device is playing anything."""


def is_available() -> bool:
    """Whether system-audio capture can be attempted at all.

    Checked rather than assumed at every call site, because "the user is on
    macOS" and "the user never installed the extra" are both ordinary states
    that must produce an explanation, not a traceback."""
    if platform.system() != "Windows":
        return False
    try:
        import pyaudiowpatch  # noqa: F401
    except ImportError:
        return False
    return True


def _default_loopback(pa):
    """The loopback device matching the current default output.

    Follows the speakers rather than taking the first loopback device in the
    list: a machine with both HDMI audio and a headset has several, and
    capturing the one nothing is playing through produces a minute of
    silence and no error - the worst kind of failure, because it looks like
    it worked.
    """
    import pyaudiowpatch as pyaudio

    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_output = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    for loopback in pa.get_loopback_device_info_generator():
        # The loopback device's name contains the output device's own name.
        if default_output["name"] in loopback["name"]:
            return loopback
    raise SystemAudioUnavailable(
        f"no loopback device found for output {default_output['name']!r}"
    )


def capture(seconds: float, stop_event=None) -> bytes:
    """Records up to `seconds` of whatever is playing, as raw 16-bit mono
    PCM at `SAMPLE_RATE`.

    `stop_event`, if given, ends the capture early when set - so "arrete" or
    a barge-in can cut a long recording short instead of the user waiting
    out a minute they no longer want.
    """
    if not is_available():
        raise SystemAudioUnavailable(
            "system audio capture needs Windows and the PyAudioWPatch package"
        )

    import numpy as np
    import pyaudiowpatch as pyaudio

    seconds = max(0.0, min(float(seconds), MAX_CAPTURE_SECONDS))
    pa = pyaudio.PyAudio()
    try:
        device = _default_loopback(pa)
        # Record at the device's own rate and channel count - WASAPI
        # loopback will not resample for us, and asking for 16kHz mono on a
        # 48kHz stereo device fails to open rather than converting.
        device_rate = int(device["defaultSampleRate"])
        channels = int(device["maxInputChannels"])
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=device_rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=CHUNK_SAMPLES,
        )
        try:
            frames = []
            total = int(device_rate * seconds)
            read = 0
            while read < total:
                if stop_event is not None and stop_event.is_set():
                    break
                chunk = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
                frames.append(np.frombuffer(chunk, dtype=np.int16))
                read += CHUNK_SAMPLES
        finally:
            stream.stop_stream()
            stream.close()
    finally:
        pa.terminate()

    if not frames:
        return b""
    audio = np.concatenate(frames)
    return _to_mono_16k(audio, channels, device_rate)


def _to_mono_16k(audio, channels: int, rate: int) -> bytes:
    """Downmixes and resamples to what the transcriber expects.

    Whisper wants 16kHz mono; the loopback device gives whatever the
    speakers run at, typically 48kHz stereo. Averaging the channels rather
    than dropping one keeps audio that was panned to a single side, which
    "take the left channel" silently loses.
    """
    import numpy as np

    if channels > 1:
        usable = (len(audio) // channels) * channels
        audio = audio[:usable].reshape(-1, channels).mean(axis=1)

    if rate != SAMPLE_RATE and len(audio) > 0:
        # Linear interpolation. A proper polyphase filter would be better
        # for music; this feeds a speech recogniser that resamples again
        # internally, so the extra dependency would buy nothing audible.
        target_len = int(len(audio) * SAMPLE_RATE / rate)
        if target_len > 0:
            audio = np.interp(
                np.linspace(0, len(audio) - 1, target_len),
                np.arange(len(audio)),
                audio,
            )
    return np.asarray(audio, dtype=np.int16).tobytes()
