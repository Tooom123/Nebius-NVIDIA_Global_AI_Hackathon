"""Trains the "Hey Peer" wake-word classifier and exports it to ONNX.

Follows openWakeWord's standard approach: the heavy melspectrogram + embedding
models are pretrained and frozen (bundled with the `openwakeword` package); only a
small classifier head is trained on top of the resulting embeddings for the new
wake phrase. This keeps training fast (CPU, minutes, no GPU required) and the
resulting head is tiny (~200 KB as ONNX).

Usage:
    python -m heypeer.wakeword.train \
        --positive-dir data/wakeword/samples/positive_augmented \
        --negative-dir data/wakeword/samples/negative_noise \
        --out data/wakeword/hey_peer.onnx
"""

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from openwakeword.utils import AudioFeatures
from sklearn.neural_network import MLPClassifier

TARGET_SR = 16000
CLIP_SECONDS = 1.5


def _load_clip(path: Path) -> np.ndarray:
    # openWakeWord's melspectrogram model expects 16-bit PCM samples, not floats.
    audio, sr = sf.read(str(path), dtype="int16", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype("int16")
    if sr != TARGET_SR:
        raise ValueError(f"{path} is {sr} Hz, expected {TARGET_SR} Hz")

    target_len = int(CLIP_SECONDS * TARGET_SR)
    if len(audio) < target_len:
        audio = np.pad(audio, (0, target_len - len(audio)))
    else:
        audio = audio[:target_len]
    return audio


def _embed_directory(wav_dir: Path, features: AudioFeatures) -> np.ndarray:
    clips = [_load_clip(p) for p in sorted(wav_dir.glob("*.wav"))]
    if not clips:
        raise FileNotFoundError(f"No wav files found in {wav_dir}")
    embeddings = features.embed_clips(np.stack(clips))
    # (n_clips, n_frames, emb_dim) -> average-pool frames into one vector per clip
    return embeddings.mean(axis=1)


def train(positive_dir: Path, negative_dir: Path) -> tuple[MLPClassifier, int]:
    features = AudioFeatures()
    pos = _embed_directory(positive_dir, features)
    neg = _embed_directory(negative_dir, features)

    x = np.concatenate([pos, neg])
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])

    clf = MLPClassifier(hidden_layer_sizes=(32,), max_iter=500, random_state=0)
    clf.fit(x, y)
    return clf, x.shape[1]


def export_onnx(clf: MLPClassifier, input_dim: int, out_path: Path) -> None:
    from skl2onnx import to_onnx

    onnx_model = to_onnx(clf, X=np.zeros((1, input_dim), dtype=np.float32))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(onnx_model.SerializeToString())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-dir", type=Path, required=True)
    parser.add_argument("--negative-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/wakeword/hey_peer.onnx"))
    args = parser.parse_args()

    clf, input_dim = train(args.positive_dir, args.negative_dir)
    export_onnx(clf, input_dim, args.out)
    print(f"Trained classifier on {input_dim}-dim embeddings, exported to {args.out}")


if __name__ == "__main__":
    main()
