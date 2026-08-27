"""Augments raw Piper samples with background noise and simple room reverb.

Consumes wavs produced by `generate_samples.py` and writes augmented copies
alongside them, so the training set contains more acoustic variety than the raw
TTS output. Negative-class background noise clips (used both as negatives and as
the augmentation noise bed) go in `data/wakeword/samples/negative_noise/`.
"""

import argparse
import random
from pathlib import Path

import numpy as np
import soundfile as sf

TARGET_SR = 16000


def _load_mono(path: Path) -> np.ndarray:
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        raise ValueError(f"{path} is {sr} Hz, expected {TARGET_SR} Hz")
    return audio


def _mix_noise(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    if len(noise) < len(speech):
        reps = int(np.ceil(len(speech) / len(noise)))
        noise = np.tile(noise, reps)
    offset = random.randint(0, len(noise) - len(speech))
    noise_segment = noise[offset : offset + len(speech)]

    speech_power = np.mean(speech**2) + 1e-10
    noise_power = np.mean(noise_segment**2) + 1e-10
    target_noise_power = speech_power / (10 ** (snr_db / 10))
    scaled_noise = noise_segment * np.sqrt(target_noise_power / noise_power)

    mixed = speech + scaled_noise
    peak = np.max(np.abs(mixed))
    return mixed / peak if peak > 1.0 else mixed


def _simple_reverb(audio: np.ndarray, decay: float = 0.3, delay_samples: int = 800) -> np.ndarray:
    """Cheap comb-filter reverb approximation — not physically accurate, just
    enough acoustic variety to help the classifier generalize past dry TTS output."""
    out = audio.copy()
    if len(out) > delay_samples:
        out[delay_samples:] += decay * audio[:-delay_samples]
    peak = np.max(np.abs(out))
    return out / peak if peak > 1.0 else out


def augment_directory(
    positive_dir: Path, noise_dir: Path, out_dir: Path, variants_per_sample: int = 2
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    noise_files = list(noise_dir.glob("*.wav"))
    if not noise_files:
        raise FileNotFoundError(f"No noise wavs found in {noise_dir}")

    count = 0
    for wav_path in positive_dir.glob("*.wav"):
        speech = _load_mono(wav_path)
        for v in range(variants_per_sample):
            noise = _load_mono(random.choice(noise_files))
            snr_db = random.uniform(5, 20)
            mixed = _mix_noise(speech, noise, snr_db)
            if random.random() < 0.5:
                mixed = _simple_reverb(mixed)
            out_path = out_dir / f"{wav_path.stem}_aug{v}.wav"
            sf.write(str(out_path), mixed, TARGET_SR)
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-dir", type=Path, default=Path("data/wakeword/samples/positive"))
    parser.add_argument("--noise-dir", type=Path, default=Path("data/wakeword/samples/negative_noise"))
    parser.add_argument("--out", type=Path, default=Path("data/wakeword/samples/positive_augmented"))
    parser.add_argument("--variants-per-sample", type=int, default=2)
    args = parser.parse_args()

    total = augment_directory(args.positive_dir, args.noise_dir, args.out, args.variants_per_sample)
    print(f"Wrote {total} augmented samples to {args.out}")


if __name__ == "__main__":
    main()
