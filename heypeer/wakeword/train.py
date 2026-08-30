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


N_ALIGNMENT_VARIANTS = 4
# Alignment variants for the user's own recordings. Higher than the default
# so ~40 real takes aren't drowned out by a few hundred synthetic clips —
# see `_embed_dirs`.
USER_ALIGNMENT_VARIANTS = 16


def _load_clip_variants(
    path: Path, rng: np.random.Generator, n_variants: int = N_ALIGNMENT_VARIANTS
) -> list[np.ndarray]:
    """Loads a clip and places it at `n_variants` random offsets within the
    fixed CLIP_SECONDS window, instead of always left-aligning it.

    Left-aligning every training clip (word at t=0, silence padding at the
    end) taught the classifier that specific alignment rather than the
    word's actual acoustic content — great held-out accuracy on identically
    left-aligned clips, but the real runtime listener feeds a continuously
    sliding buffer that visits every alignment as speech moves through it,
    and mis-aligned windows produced spurious high scores on prior versions
    of this model (verified: a plain negative phrase padded with leading
    silence — an alignment never seen in training — scored ~1.0 streamed,
    but ~0.0 loaded left-aligned). Randomizing the offset during training
    for both positive and negative clips directly targets that mismatch.
    """
    # openWakeWord's melspectrogram model expects 16-bit PCM samples, not floats.
    audio, sr = sf.read(str(path), dtype="int16", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype("int16")
    if sr != TARGET_SR:
        raise ValueError(f"{path} is {sr} Hz, expected {TARGET_SR} Hz")

    target_len = int(CLIP_SECONDS * TARGET_SR)
    if len(audio) > target_len:
        audio = audio[:target_len]
    max_offset = target_len - len(audio)

    variants = []
    for _ in range(n_variants):
        offset = int(rng.integers(0, max_offset + 1)) if max_offset > 0 else 0
        clip = np.zeros(target_len, dtype=np.int16)
        clip[offset : offset + len(audio)] = audio
        variants.append(clip)
    return variants


def _embed_directory(
    wav_dir: Path,
    features: AudioFeatures,
    rng: np.random.Generator,
    n_variants: int = N_ALIGNMENT_VARIANTS,
) -> np.ndarray:
    paths = sorted(wav_dir.glob("*.wav"))
    if not paths:
        raise FileNotFoundError(f"No wav files found in {wav_dir}")
    clips = [clip for p in paths for clip in _load_clip_variants(p, rng, n_variants)]
    embeddings = features.embed_clips(np.stack(clips))
    # (n_clips, n_frames, emb_dim) -> average-pool frames into one vector per clip
    return embeddings.mean(axis=1)


def _embed_dirs(
    wav_dirs: "list[Path]",
    features: AudioFeatures,
    rng: np.random.Generator,
    user_variants: int,
) -> np.ndarray:
    """Embeds several directories into one array.

    Directories whose name contains "user" get more alignment variants. A
    personalised model is trained on maybe 40 real recordings against a few
    hundred synthetic ones, and at equal weighting the real voice — the whole
    point of recording it — barely moves the decision boundary. Oversampling
    through *more random alignments* rather than duplicated rows adds genuine
    variation instead of just repeating identical vectors.
    """
    arrays = []
    for wav_dir in wav_dirs:
        variants = user_variants if "user" in wav_dir.name else N_ALIGNMENT_VARIANTS
        arrays.append(_embed_directory(wav_dir, features, rng, variants))
    return np.concatenate(arrays)


def train(
    positive_dirs: "Path | list[Path]",
    negative_dirs: "Path | list[Path]",
    seed: int = 0,
    user_variants: int = USER_ALIGNMENT_VARIANTS,
) -> tuple[MLPClassifier, int]:
    if isinstance(positive_dirs, Path):
        positive_dirs = [positive_dirs]
    if isinstance(negative_dirs, Path):
        negative_dirs = [negative_dirs]

    features = AudioFeatures()
    rng = np.random.default_rng(seed)
    pos = _embed_dirs(positive_dirs, features, rng, user_variants)
    neg = _embed_dirs(negative_dirs, features, rng, user_variants)

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
    parser.add_argument(
        "--positive-dir", type=Path, required=True, action="append",
        help="repeatable; a directory whose name contains 'user' is weighted higher",
    )
    parser.add_argument("--negative-dir", type=Path, required=True, action="append")
    parser.add_argument("--out", type=Path, default=Path("data/wakeword/hey_peer.onnx"))
    args = parser.parse_args()

    clf, input_dim = train(args.positive_dir, args.negative_dir)
    export_onnx(clf, input_dim, args.out)
    print(f"Trained classifier on {input_dim}-dim embeddings, exported to {args.out}")


if __name__ == "__main__":
    main()
