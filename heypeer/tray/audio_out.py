"""Shared audio output, so playback doesn't pay for PortAudio every time.

Both the activation chime and every spoken line used to construct their own
`pyaudio.PyAudio()`, play, then `terminate()`. That constructor initialises
PortAudio and enumerates the host API's devices — on Windows a few hundred
milliseconds, sometimes more — and it ran once per utterance. The user hears
that as the voice arriving late, since it sits between deciding what to say
and the first sample coming out.

The instance is created once and kept. Streams are still opened per playback:
opening one is far cheaper than initialising PortAudio, and holding an output
stream open indefinitely keeps the device claimed for no good reason.

Playback is serialised with a lock. The chime plays from the wake-word audio
thread while speech plays from the turn handler, and PortAudio is not
reliably safe for concurrent stream operations across threads. They don't
overlap in practice — the chime fires at the trigger, speech once an action
is resolved — so serialising costs nothing and removes the hazard.
"""

import atexit
import threading

_pyaudio = None
_lock = threading.Lock()


def _instance():
    """The process-wide PyAudio instance, created on first use."""
    global _pyaudio
    if _pyaudio is None:
        import pyaudio

        _pyaudio = pyaudio.PyAudio()
        atexit.register(_shutdown)
    return _pyaudio


def _shutdown() -> None:
    global _pyaudio
    if _pyaudio is not None:
        try:
            _pyaudio.terminate()
        except Exception:
            pass
        _pyaudio = None


def warm_up() -> bool:
    """Initialises PortAudio ahead of time. Called during preload so the
    first chime or spoken line doesn't pay for it. Returns whether it
    worked; a machine with no output device is not an error worth raising
    from a background warm-up."""
    try:
        _instance()
        return True
    except Exception:
        return False


def play(samples: bytes, rate: int, sample_width: int = 2, channels: int = 1) -> None:
    """Plays raw PCM through the default output device, blocking until done."""
    with _lock:
        pa = _instance()
        stream = pa.open(
            format=pa.get_format_from_width(sample_width),
            channels=channels,
            rate=rate,
            output=True,
        )
        try:
            stream.write(samples)
        finally:
            stream.stop_stream()
            stream.close()
