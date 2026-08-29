"""Generates negative-class training data for the "Hey Peer" wake word:
synthetic speech saying anything *but* "Hey Peer" (the confusable case that
matters most), plus plain noise clips (used both as negatives and as the
noise bed for `augment.py`).

Usage:
    python -m heypeer.wakeword.generate_negatives \
        --voices data/wakeword/piper_voices/*.onnx \
        --n-per-voice 40 --out data/wakeword/samples/negative_noise
"""

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

from heypeer.wakeword.generate_samples import TARGET_SR, _synth_one

# Short, everyday phrases distinct from "Hey Peer" — the wake-word classifier
# most needs to reject phonetically-similar/short utterances like these, not
# just silence or noise. A first pass with only ~20 phrases (repeated many
# times per voice) let the classifier score some of them almost identically
# to "Hey Peer" during real streaming — not a brief blip, a sustained
# multi-frame plateau — because it had only ever seen 20 distinct negative
# word contents. This list is deliberately large and varied in length (single
# words up to full sentences) so training sees far more distinct content
# instead of the same handful of phrases repeated.
NEGATIVE_PHRASES = [
    "turn on the light",
    "what time is it",
    "hello there",
    "good morning",
    "play some music",
    "hey Google",
    "hey Siri",
    "hi Peter",
    "hey there",
    "okay computer",
    "stop that",
    "close the window",
    "open the door",
    "how are you",
    "thank you very much",
    "see you later",
    "check the weather",
    "set a timer",
    "call my mother",
    "read my messages",
    "hey",
    "hi",
    "peer",
    "clear",
    "hey pier",
    "hey bear",
    "hey dear",
    "hey fear",
    "hey year",
    "hey there friend",
    "yes",
    "no",
    "maybe later",
    "not now",
    "wait a second",
    "come here",
    "go away",
    "turn it off",
    "increase the volume",
    "lower the volume",
    "pause the video",
    "resume playback",
    "next song please",
    "previous track",
    "add to my list",
    "remove that item",
    "send this email",
    "delete this file",
    "rename the folder",
    "copy that text",
    "paste it here",
    "undo my last action",
    "redo that",
    "save the document",
    "print this page",
    "search the web",
    "open the browser",
    "close this window",
    "minimize the app",
    "maximize the screen",
    "switch to the other tab",
    "lock my computer",
    "log out now",
    "restart the machine",
    "shut down please",
    "connect to wifi",
    "disable bluetooth",
    "increase brightness",
    "decrease brightness",
    "mute the microphone",
    "unmute the speaker",
    "start recording",
    "stop recording",
    "take a screenshot",
    "open my calendar",
    "schedule a meeting",
    "cancel the appointment",
    "remind me tomorrow",
    "what's the news today",
    "tell me a joke",
    "how far is the moon",
    "translate this sentence",
    "spell that word",
    "define this term",
    "calculate the total",
    "convert to euros",
    "good night",
    "see you tomorrow",
    "nice to meet you",
    "excuse me please",
    "sorry about that",
    "no worries",
    "sounds good",
    "let's get started",
    "almost done",
    "one moment please",
]


def _generate_speech_negatives(voice_paths: list[Path], out_dir: Path) -> int:
    """One clip per (voice, phrase) pair, covering every phrase in
    NEGATIVE_PHRASES rather than randomly sampling with repeats — the point
    is maximizing distinct negative *content*, not clip count."""
    from piper import PiperVoice

    count = 0
    for voice_path in voice_paths:
        voice_name = voice_path.stem
        voice = PiperVoice.load(str(voice_path))
        for i, phrase in enumerate(NEGATIVE_PHRASES):
            out_path = out_dir / f"neg_{voice_name}_{i:04d}.wav"
            _synth_one(voice, phrase, out_path, seed=hash((voice_name, "neg", i)))
            count += 1
    return count


def _generate_noise_clips(n_clips: int, out_dir: Path, duration_s: float = 1.5) -> int:
    rng = np.random.default_rng(0)
    n_samples = int(duration_s * TARGET_SR)
    for i in range(n_clips):
        kind = i % 3
        if kind == 0:
            noise = rng.standard_normal(n_samples)  # white noise
        elif kind == 1:
            white = rng.standard_normal(n_samples)  # pink-ish: 1/f-weighted
            freqs = np.fft.rfftfreq(n_samples)
            freqs[0] = freqs[1]
            spectrum = np.fft.rfft(white) / np.sqrt(freqs)
            noise = np.fft.irfft(spectrum, n_samples)
        else:
            t = np.linspace(0, duration_s, n_samples, endpoint=False)
            noise = 0.3 * np.sin(2 * np.pi * rng.uniform(50, 400) * t)  # low hum/rumble
        noise = noise / (np.max(np.abs(noise)) + 1e-9) * 0.3
        audio = (noise * 32767).astype(np.int16)
        sf.write(str(out_dir / f"noise_{i:04d}.wav"), audio, TARGET_SR)
    return n_clips


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", nargs="+", required=True, type=Path)
    parser.add_argument("--n-noise-clips", type=int, default=60)
    parser.add_argument(
        "--out", type=Path, default=Path("data/wakeword/samples/negative_noise")
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    speech_count = _generate_speech_negatives(args.voices, args.out)
    noise_count = _generate_noise_clips(args.n_noise_clips, args.out)
    print(f"Generated {speech_count} speech negatives + {noise_count} noise clips in {args.out}")


if __name__ == "__main__":
    main()
