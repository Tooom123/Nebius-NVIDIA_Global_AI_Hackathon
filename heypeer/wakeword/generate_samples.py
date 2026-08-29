"""Generate synthetic "Hey Peer" utterances with Piper TTS for wake-word training.

Requires the `piper-tts` package and at least one downloaded Piper voice (`.onnx` +
`.onnx.json`). Voices can be fetched with:

    python -c "from piper import download_voices as d; from pathlib import Path; \
        d.download_voice('en_US-lessac-medium', Path('data/wakeword/piper_voices'))"

(browse available voice names at https://huggingface.co/rhasspy/piper-voices)

Usage:
    python -m heypeer.wakeword.generate_samples \
        --voices data/wakeword/piper_voices/en_US-lessac-medium.onnx ... \
        --phrase "hey peer" --n-per-voice 60 --out data/wakeword/samples/positive

Piper synthesizes at each voice's native sample rate (typically 22050 Hz) — this
resamples to 16 kHz mono int16, which is what the rest of the wake-word pipeline
(`train.py`, `listener.py`) expects. This does not itself train anything — it only
produces the raw positive-class wav files consumed by `heypeer/wakeword/train.py`.
"""

import argparse
import io
import random
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

TARGET_SR = 16000

PHRASE_VARIANTS = [
    "hey peer",
    "Hey Peer",
    "hey, peer",
    "hey peer.",
    "hey peer!",
]

# length_scale controls speaking rate, noise_scale/noise_w_scale control prosody
# variation — jittering them gives acoustic variety beyond just voice identity.
PARAM_JITTER = {
    "length_scale": (0.85, 1.2),
    "noise_scale": (0.5, 0.9),
    "noise_w_scale": (0.5, 0.9),
}


def _resample_to_16k(pcm_bytes: bytes, src_rate: int) -> np.ndarray:
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    if src_rate == TARGET_SR:
        return audio.astype(np.int16)
    resampled = resample_poly(audio, TARGET_SR, src_rate)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def _synth_one(voice, text: str, out_path: Path, seed: int) -> None:
    from piper.config import SynthesisConfig

    rng = random.Random(seed)
    syn_config = SynthesisConfig(
        length_scale=rng.uniform(*PARAM_JITTER["length_scale"]),
        noise_scale=rng.uniform(*PARAM_JITTER["noise_scale"]),
        noise_w_scale=rng.uniform(*PARAM_JITTER["noise_w_scale"]),
    )

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=syn_config)
    buffer.seek(0)
    with wave.open(buffer, "rb") as wav_file:
        src_rate = wav_file.getframerate()
        pcm_bytes = wav_file.readframes(wav_file.getnframes())

    audio_16k = _resample_to_16k(pcm_bytes, src_rate)
    sf.write(str(out_path), audio_16k, TARGET_SR, subtype="PCM_16")


def generate(
    voice_model_paths: list[Path], phrase: str, n_per_voice: int, out_dir: Path
) -> int:
    from piper import PiperVoice

    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for voice_path in voice_model_paths:
        voice_name = voice_path.stem
        voice = PiperVoice.load(str(voice_path))
        for i in range(n_per_voice):
            text = random.choice(PHRASE_VARIANTS) if phrase == "hey peer" else phrase
            out_path = out_dir / f"{voice_name}_{i:04d}.wav"
            _synth_one(voice, text, out_path, seed=hash((voice_name, i)))
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
