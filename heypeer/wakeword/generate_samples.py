"""Generate synthetic "Hey Peer" utterances with Piper TTS for wake-word training.

Requires the `piper-tts` package and at least one downloaded Piper voice (`.onnx` +
`.onnx.json`). Voices: https://github.com/rhasspy/piper/blob/master/VOICES.md

Usage:
    python -m heypeer.wakeword.generate_samples \
        --voices en_US-lessac-medium en_US-amy-medium en_US-ryan-medium \
        --phrase "hey peer" --n-per-voice 60 --out data/wakeword/samples/positive

This does not itself train anything — it only produces the raw positive-class wav
files consumed by `heypeer/wakeword/train.py`.
"""

import argparse
import random
import wave
from pathlib import Path

PHRASE_VARIANTS = [
    "hey peer",
    "Hey Peer",
    "hey, peer",
    "hey peer.",
    "hey peer!",
]

# length_scale controls speaking rate, noise_scale/noise_w control prosody variation.
# Piper accepts these as synthesis-time parameters.
PARAM_JITTER = {
    "length_scale": (0.85, 1.2),
    "noise_scale": (0.5, 0.9),
    "noise_w": (0.5, 0.9),
}


def _synth_one(
    voice_model_path: Path, text: str, out_path: Path, seed: int
) -> None:
    from piper import PiperVoice

    rng = random.Random(seed)
    voice = PiperVoice.load(str(voice_model_path))

    with wave.open(str(out_path), "wb") as wav_file:
        voice.synthesize_wav(
            text,
            wav_file,
            length_scale=rng.uniform(*PARAM_JITTER["length_scale"]),
            noise_scale=rng.uniform(*PARAM_JITTER["noise_scale"]),
            noise_w=rng.uniform(*PARAM_JITTER["noise_w"]),
        )


def generate(
    voice_model_paths: list[Path], phrase: str, n_per_voice: int, out_dir: Path
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for voice_path in voice_model_paths:
        voice_name = voice_path.stem
        for i in range(n_per_voice):
            text = random.choice(PHRASE_VARIANTS) if phrase == "hey peer" else phrase
            out_path = out_dir / f"{voice_name}_{i:04d}.wav"
            _synth_one(voice_path, text, out_path, seed=hash((voice_name, i)))
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--voices",
        nargs="+",
        required=True,
        help="Paths to Piper voice .onnx model files",
        type=Path,
    )
    parser.add_argument("--phrase", default="hey peer")
    parser.add_argument("--n-per-voice", type=int, default=60)
    parser.add_argument(
        "--out", type=Path, default=Path("data/wakeword/samples/positive")
    )
    args = parser.parse_args()

    total = generate(args.voices, args.phrase, args.n_per_voice, args.out)
    print(f"Generated {total} positive samples in {args.out}")


if __name__ == "__main__":
    main()
