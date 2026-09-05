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

# Set to ask whatever is currently playing to stop early. Cleared at the
# start of every `play`, so a stop only ever cancels the utterance it was
# raised against - never a later one that happens to start afterwards.
_stop = threading.Event()

# How much audio is handed to PortAudio at a time. `stream.write` blocks
# until the chunk has been consumed, so this is also the granularity at
# which a stop request can be noticed: the tail already handed over still
# plays. 1024 frames is ~46ms at 22.05kHz - below the ~100ms at which a cut
# stops sounding immediate, and large enough not to risk an underrun.
CHUNK_FRAMES = 1024


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


def stop() -> None:
    """Asks the utterance currently playing to stop as soon as it can.

    Safe to call when nothing is playing: the flag is cleared by the next
    `play`, so it cannot leak into a later utterance."""
    _stop.set()


def play(samples: bytes, rate: int, sample_width: int = 2, channels: int = 1) -> bool:
    """Plays raw PCM through the default output device, blocking until done.

    Returns True if the whole thing played, False if `stop` cut it short.

    Written in chunks rather than one `stream.write(samples)` so that it can
    be interrupted at all. Being unable to talk over the assistant is the
    single most-cited complaint about voice assistants, and a blocking write
    of a whole utterance offers nowhere to check whether the user wants to
    interject: the caller is stuck until the last sample is out.
    """
    with _lock:
        _stop.clear()
        pa = _instance()
        stream = pa.open(
            format=pa.get_format_from_width(sample_width),
            channels=channels,
            rate=rate,
            output=True,
        )
        chunk_bytes = CHUNK_FRAMES * sample_width * channels
        try:
            for start in range(0, len(samples), chunk_bytes):
                if _stop.is_set():
                    return False
                stream.write(samples[start : start + chunk_bytes])
            return True
        finally:
            stream.stop_stream()
            stream.close()
