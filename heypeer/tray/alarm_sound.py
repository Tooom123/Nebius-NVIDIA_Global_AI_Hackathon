"""The sound a timer makes when it comes due.

## Why it is synthesised rather than a file

A jingle is a few hundred bytes of arithmetic and a few hundred kilobytes as
audio. Generating it means nothing to ship, nothing to license, and - the
part that actually matters here - it can be built to match the product:
three rising notes on the same intervals, repeated, so it reads as "a
thing finished" rather than as a generic alert.

It is also the only way to keep it *interruptible* cheaply. The alarm
repeats until the user stops it, and a repeating file needs a player loop
around it; a generated buffer is just played again, through the same
`audio_out.play` every other sound already goes through, which already
knows how to be cut short.

## The sound

A major triad arpeggio - root, third, fifth - each note a short sine with a
soft attack and a long decay. Sine rather than square or saw because this
plays over whatever the user is listening to, and a harmonically rich tone
cuts through music in a way that is useful for a smoke alarm and rude for a
pasta timer. The envelope is what stops it clicking: an instantaneous start
on a sine is a step in the waveform, and a step is a click.
"""

import math

SAMPLE_RATE = 22050

# A major triad in the fourth octave: A4, C#5, E5. Chosen to sit above
# speech and below the frequencies that feel piercing - it has to be
# audible from another room without being unpleasant in the same one.
NOTES = (440.0, 554.37, 659.25)

NOTE_SECONDS = 0.16
GAP_SECONDS = 0.06
# Silence after the arpeggio, before it repeats. Long enough that the
# repetition is clearly a repetition rather than a stutter.
TAIL_SECONDS = 0.9

AMPLITUDE = 0.28  # room to be heard, well below clipping

# How many arpeggios go into one playable buffer, and how many of those
# buffers play before the alarm gives up on its own. Together about ninety
# seconds - long enough to be heard from another room, bounded so a timer
# nobody is there for does not ring until the machine is switched off.
#
# Built as bursts rather than one long buffer because `audio_out.play`
# checks for a stop between chunks: a burst is the granularity at which
# "stopped between sounds" is noticed, and three arpeggios is short enough
# that pressing stop feels immediate.
REPEATS_PER_BURST = 3
MAX_BURSTS = 10


def _envelope(n: int, total: int) -> float:
    """Attack-decay shape for one note, 0 at both ends.

    Zero at both ends is the whole point: a sine that starts or stops at
    non-zero amplitude is a step in the waveform, and a step is an audible
    click. The attack is short and the decay long, which is what makes a
    plucked note rather than a beep.
    """
    attack = max(1, int(total * 0.08))
    if n < attack:
        return n / attack
    return (1.0 - (n - attack) / max(1, total - attack)) ** 1.6


def render(repeats: int = 1) -> bytes:
    """The jingle as raw 16-bit mono PCM at `SAMPLE_RATE`.

    `repeats` plays the arpeggio more than once in a single buffer, which is
    how the alarm keeps sounding without a player loop.
    """
    import numpy as np

    note_len = int(SAMPLE_RATE * NOTE_SECONDS)
    gap = np.zeros(int(SAMPLE_RATE * GAP_SECONDS), dtype=np.float32)
    tail = np.zeros(int(SAMPLE_RATE * TAIL_SECONDS), dtype=np.float32)

    parts = []
    for _ in range(max(1, repeats)):
        for frequency in NOTES:
            t = np.arange(note_len, dtype=np.float32) / SAMPLE_RATE
            wave = np.sin(2 * math.pi * frequency * t)
            env = np.array(
                [_envelope(i, note_len) for i in range(note_len)], dtype=np.float32
            )
            parts.append(wave * env * AMPLITUDE)
            parts.append(gap)
        parts.append(tail)

    audio = np.concatenate(parts)
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
