"""Builds the film's sound-effects track, assets/sfx/sfx.wav.

Every sound is synthesised here from sines and seeded noise, so there is no
third-party audio and nothing to license. The cue times follow the GSAP
timeline in index.html: move a tween there, move its cue here, and run

    python motion/sfx/build_sfx.py
"""

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

SR = 48000
LENGTH = 57.0
OUT = Path(__file__).resolve().parent.parent / "assets" / "sfx" / "sfx.wav"
rng = np.random.default_rng(7)


def t_axis(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def decay(dur: float, tau: float, attack: float = 0.002) -> np.ndarray:
    t = t_axis(dur)
    return np.minimum(t / attack, 1.0) * np.exp(-t / tau)


def sweep(f0: float, f1: float, dur: float) -> np.ndarray:
    """Phase of a sine gliding exponentially from f0 to f1."""
    t = t_axis(dur)
    freq = f0 * (f1 / f0) ** (t / dur)
    return 2 * np.pi * np.cumsum(freq) / SR


# --- The sounds -----------------------------------------------------------

def tick(freq: float = 2400, gain: float = 0.16) -> np.ndarray:
    """A small glassy UI tick."""
    dur = 0.09
    t = t_axis(dur)
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 2.01 * t)
    return gain * tone * decay(dur, 0.014)


def pop(freq: float = 560, gain: float = 0.32) -> np.ndarray:
    """A soft rounded pop: a sine that drops into place."""
    dur = 0.16
    tone = np.sin(sweep(freq * 1.8, freq, dur)) + 0.25 * np.sin(2 * sweep(freq * 1.8, freq, dur))
    return gain * tone * decay(dur, 0.035, attack=0.003)


def click(gain: float = 0.28) -> np.ndarray:
    """A mouse click: a sharp noise transient and a tiny resonance."""
    dur = 0.03
    t = t_axis(dur)
    sos = signal.butter(2, 2500, "highpass", fs=SR, output="sos")
    noise = signal.sosfilt(sos, rng.standard_normal(len(t))) * decay(dur, 0.0025, attack=0.0002)
    body = 0.5 * np.sin(2 * np.pi * 3100 * t) * decay(dur, 0.005, attack=0.0002)
    return gain * (noise + body)


def whoosh(dur: float, f0: float, f1: float, gain: float = 0.22, peak: float = 0.6) -> np.ndarray:
    """Band-passed noise whose centre glides from f0 to f1, swelling then fading."""
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    block = 512
    centres = f0 * (f1 / f0) ** (np.arange(0, n, block) / n)
    zi = None
    for i, c in enumerate(centres):
        sos = signal.butter(2, [c / 1.6, c * 1.6], "bandpass", fs=SR, output="sos")
        if zi is None:
            zi = signal.sosfilt_zi(sos) * 0
        seg = slice(i * block, min((i + 1) * block, n))
        out[seg], zi = signal.sosfilt(sos, noise[seg], zi=zi)
    x = np.linspace(0, 1, n)
    env = np.where(x < peak, np.sin(np.pi / 2 * x / peak) ** 2,
                   np.cos(np.pi / 2 * (x - peak) / (1 - peak)) ** 2)
    return gain * out / (np.abs(out).max() + 1e-9) * env


def chime(notes: "list[float]", gap: float = 0.06, gain: float = 0.14, tail: float = 1.6) -> np.ndarray:
    """Bell-like notes rolled one after another."""
    dur = tail + gap * len(notes)
    out = np.zeros(int(dur * SR))
    for i, f in enumerate(notes):
        t = t_axis(tail)
        tone = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2.0 * t + 0.3)
                + 0.12 * np.sin(2 * np.pi * f * 3.01 * t))
        # Two slightly detuned voices, for a little shimmer.
        tone += 0.5 * np.sin(2 * np.pi * f * 1.003 * t)
        start = int(i * gap * SR)
        out[start:start + len(t)] += tone * decay(tail, tail / 4.5, attack=0.004)
    return gain * out / len(notes) ** 0.5


def swell(dur: float, base: float = 110, gain: float = 0.12) -> np.ndarray:
    """A low, soft pad that breathes in and out."""
    t = t_axis(dur)
    tone = sum(a * np.sin(2 * np.pi * base * m * t) for m, a in [(1, 1), (1.5, 0.5), (2, 0.35), (3, 0.12)])
    env = np.sin(np.pi * np.linspace(0, 1, len(t))) ** 2
    return gain * tone * env


def blip(f0: float, f1: float, dur: float = 0.5, gain: float = 0.12) -> np.ndarray:
    """A data packet travelling: a gliding sine with a soft envelope."""
    env = np.sin(np.pi * np.linspace(0, 1, int(dur * SR))) ** 1.5
    return gain * np.sin(sweep(f0, f1, dur)) * env


def thump(gain: float = 0.45) -> np.ndarray:
    dur = 0.4
    return gain * np.sin(sweep(95, 42, dur)) * decay(dur, 0.09, attack=0.002)


# --- Placing them -----------------------------------------------------------

track = np.zeros((int(LENGTH * SR) + SR, 2))


def put(at: float, sound: np.ndarray, pan: float = 0.0, pan_to: "float | None" = None) -> None:
    """Adds `sound` at `at` seconds, panned -1 (left) to 1 (right), optionally moving."""
    start = int(at * SR)
    p = np.full(len(sound), pan) if pan_to is None else np.linspace(pan, pan_to, len(sound))
    left = np.cos((p + 1) * np.pi / 4)
    right = np.sin((p + 1) * np.pi / 4)
    track[start:start + len(sound), 0] += sound * left
    track[start:start + len(sound), 1] += sound * right


E5, GS5, B5, CS6, E6, FS6, GS6 = 659.25, 830.61, 987.77, 1108.73, 1318.5, 1479.98, 1661.2
SIGNATURE = [E5, GS5, B5, E6]
PENTA = [1318.5, 1479.98, 1661.2, 1975.5, 2217.5, 2637.0]

# 1. Opening: the blob wakes, the name lands, the promise rings.
put(0.05, swell(2.2, base=82.4, gain=0.14))
put(0.3, chime([B5, E6, GS6], gap=0.09, gain=0.08, tail=2.0))
put(1.7, whoosh(0.7, 900, 3200, gain=0.07))
put(3.42, chime(SIGNATURE, gap=0.07, gain=0.16))
put(4.6, whoosh(0.8, 2400, 500, gain=0.12))

# 2. The problem: every app wants a click.
for i, (t, p) in enumerate(zip([5.9 + 0.22 * k for k in range(6)], [-0.6, 0.7, -0.2, 0.4, -0.7, 0.6])):
    put(t, click(gain=0.22 + 0.02 * (i % 2)), pan=p)
put(8.8, whoosh(0.8, 2400, 500, gain=0.12))

# 3. No mouse, no keyboard.
put(9.45, pop(520), pan=-0.25)
put(9.57, pop(600), pan=0.25)
put(9.95, whoosh(0.3, 5000, 1800, gain=0.12, peak=0.3), pan=-0.25)
put(10.4, whoosh(0.3, 5000, 1800, gain=0.12, peak=0.3), pan=0.25)
put(11.0, whoosh(0.6, 600, 2400, gain=0.08, peak=0.8))
put(11.3, chime([E6, GS6], gap=0.08, gain=0.07, tail=1.4))
put(12.8, whoosh(0.8, 2400, 500, gain=0.12))

# 4. The pipeline.
put(13.45, swell(1.8, base=110, gain=0.09))
put(13.9, pop(620, 0.24), pan=-0.3)
put(14.6, tick(2000, 0.1), pan=-0.3)
put(14.85, pop(700, 0.24), pan=-0.3)
put(15.4, pop(780, 0.24), pan=-0.3)
put(18.55, whoosh(1.2, 500, 1600, gain=0.11), pan=-0.5, pan_to=0.3)
put(19.0, blip(700, 1500, 0.75), pan=-0.4, pan_to=0.0)
put(19.5, thump(0.35))
put(19.55, chime([E5, B5], gap=0.05, gain=0.09, tail=1.8))
for i in range(5):
    put(20.7 + 0.42 * i, tick(PENTA[i], 0.08))
put(24.35, whoosh(1.2, 500, 1600, gain=0.11), pan=-0.3, pan_to=0.5)
for i in range(5):
    put(24.9 + 0.4 * i, tick(PENTA[i] * 0.75, 0.06), pan=0.5)
    put(25.2 + 0.4 * i, pop(560 + 70 * i, 0.2), pan=0.5)
put(27.85, whoosh(1.6, 1800, 400, gain=0.13, peak=0.45))
put(29.3, blip(1400, 900, 0.55), pan=0.5, pan_to=0.1)
put(29.8, chime([B5, E6], gap=0.05, gain=0.07, tail=1.2))
put(30.3, blip(1300, 700, 0.65), pan=0.0, pan_to=-0.4)
put(30.9, chime([GS5, B5, E6], gap=0.06, gain=0.09, tail=1.6), pan=-0.3)
put(33.6, whoosh(0.8, 2400, 500, gain=0.12))

# 5. Personal AI: each card takes the light.
for i in range(4):
    pan = -0.6 + 0.4 * i
    put(34.9 + 2.1 * i, pop(500 + 60 * i, 0.26), pan=pan)
    put(35.0 + 2.1 * i, chime([[E6, FS6, GS6, B5 * 2][i]], gain=0.05, tail=1.0), pan=pan)
put(43.85, whoosh(0.8, 2400, 500, gain=0.12))

# 6. Built to be trusted: the counter ticks up to 1000+.
put(45.0, thump(0.3), pan=-0.3)
for k in range(1, 10):
    p = 1 - np.sqrt(1 - k / 10)
    put(45.4 + 1.4 * p, tick(1600 * 2 ** (k / 12), 0.09), pan=0.3)
put(46.6, pop(640, 0.22))
put(46.78, chime(SIGNATURE, gap=0.05, gain=0.12, tail=1.5), pan=0.2)
put(49.85, whoosh(0.8, 2400, 500, gain=0.12))

# 7. End: the blob returns, the signature rings once more, and it sinks away.
put(50.4, swell(2.4, base=82.4, gain=0.14))
put(50.6, chime([B5, E6, GS6], gap=0.09, gain=0.08, tail=2.0))
put(51.98, chime(SIGNATURE, gap=0.07, gain=0.16))
put(55.5, whoosh(1.4, 1600, 300, gain=0.12, peak=0.35))

# A short synthetic room, so the sounds share one space.
ir_t = t_axis(0.9)
for ch in range(2):
    ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t / 0.18)
    ir /= np.abs(ir).sum() ** 0.5 * 6
    track[:, ch] += 0.35 * signal.fftconvolve(track[:, ch], ir)[: len(track)]

track = track[: int(LENGTH * SR)]
fade = int(0.4 * SR)
track[-fade:] *= np.linspace(1, 0, fade)[:, None]
track *= 10 ** (-3 / 20) / np.abs(track).max()

OUT.parent.mkdir(parents=True, exist_ok=True)
sf.write(OUT, track.astype(np.float32), SR, subtype="PCM_24")
print(f"{OUT} ({LENGTH:.0f} s)")
