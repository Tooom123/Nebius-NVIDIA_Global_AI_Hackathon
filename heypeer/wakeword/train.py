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

# Where the pipeline puts its samples. Used as defaults so retraining needs
# no path arguments at all — see `_default_dirs`.
_SAMPLES = Path("data/wakeword/samples")
DEFAULT_POSITIVE_DIRS = [_SAMPLES / "positive_user", _SAMPLES / "positive_augmented"]
DEFAULT_NEGATIVE_DIRS = [_SAMPLES / "negative_user", _SAMPLES / "negative_noise"]


def _load_clip_variants(
    path: Path,
    rng: np.random.Generator,
    n_variants: int = N_ALIGNMENT_VARIANTS,
    center_on_speech: bool = True,
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

    if not center_on_speech and len(audio) > target_len:
        # Negatives: sample windows across the whole recording, deliberately
        # including ones that straddle its start and end.
        #
        # A positive clip is "silence, a short word, silence" — and the
        # *onset* of any sentence has exactly that shape. Training negatives
        # only on their loudest, fully-voiced stretch means the model never
        # sees a speech onset labelled "not the wake word", so every onset
        # scores high. That is what left negatives at 1.00 after silence was
        # already fixed. These partial windows are also precisely what the
        # live listener sees as someone starts talking.
        return _sliding_windows(audio, target_len, n_variants, rng)

    if len(audio) > target_len:
        audio = _loudest_window(audio, target_len)
    max_offset = target_len - len(audio)

    variants = []
    for _ in range(n_variants):
        offset = int(rng.integers(0, max_offset + 1)) if max_offset > 0 else 0
        clip = np.zeros(target_len, dtype=np.int16)
        clip[offset : offset + len(audio)] = audio
        variants.append(clip)
    return variants


def _sliding_windows(
    audio: np.ndarray, target_len: int, n: int, rng: np.random.Generator
) -> "list[np.ndarray]":
    """`n` windows sampled across `audio`, allowed to hang off either end
    (the overhang is silence), so onsets and offsets are represented."""
    lowest = -target_len // 2
    highest = len(audio) - target_len // 2
    windows = []
    for _ in range(n):
        start = int(rng.integers(lowest, highest + 1))
        clip = np.zeros(target_len, dtype=np.int16)
        src_start = max(0, start)
        src_end = min(len(audio), start + target_len)
        if src_end > src_start:
            clip[src_start - start : src_end - start] = audio[src_start:src_end]
        windows.append(clip)
    return windows


def _loudest_window(audio: np.ndarray, target_len: int) -> np.ndarray:
    """The `target_len` slice carrying the most energy.

    Recorded takes are longer than the training window and the speaker does
    not start on the first sample — after a countdown people typically begin
    a few hundred milliseconds in. Blindly keeping the first `target_len`
    samples therefore cut the wake word out of its own training clip and kept
    the silence in front of it.
    """
    step = target_len // 8
    best_start, best_energy = 0, -1.0
    for start in range(0, len(audio) - target_len + 1, max(1, step)):
        energy = float(np.abs(audio[start : start + target_len].astype(np.int64)).sum())
        if energy > best_energy:
            best_start, best_energy = start, energy
    return audio[best_start : best_start + target_len]


def _silence_and_noise_clips(rng: np.random.Generator, n: int = 60) -> "list[np.ndarray]":
    """Silence and faint noise, always added to the negative class.

    Not optional, and not a nicety: a wake-word model has to reject silence,
    because a live listener spends nearly all its time looking at exactly
    that. Training without it produced a model that scored 1.0 on pure
    silence — every clip then peaked at 1.0 somewhere and no threshold could
    separate anything. Generating these here means the guarantee holds
    whatever the user happens to have recorded.
    """
    target_len = int(CLIP_SECONDS * TARGET_SR)
    clips = [np.zeros(target_len, dtype=np.int16) for _ in range(n // 3)]
    for _ in range(n - len(clips)):
        # Faint broadband noise across a range of levels, covering quiet
        # rooms through to a noticeable fan or hiss.
        amplitude = float(rng.uniform(0.0005, 0.03))
        clips.append((rng.standard_normal(target_len) * amplitude * 32767).astype(np.int16))
    return clips


def _embed_directory(
    wav_dir: Path,
    features: AudioFeatures,
    rng: np.random.Generator,
    n_variants: int = N_ALIGNMENT_VARIANTS,
    center_on_speech: bool = True,
) -> np.ndarray:
    if not wav_dir.is_dir():
        # Distinguished from "empty" on purpose: the usual cause is a
        # mistyped path, and on Git Bash a Windows-style `data\wakeword\...`
        # silently loses its backslashes (they are escape characters there),
        # producing a nonsense directory name that is hard to spot.
        raise FileNotFoundError(
            f"No such directory: {wav_dir}\n"
            "        (if you are on Git Bash, use forward slashes: "
            "data/wakeword/samples/...)"
        )
    paths = sorted(wav_dir.glob("*.wav"))
    if not paths:
        raise FileNotFoundError(f"No wav files found in {wav_dir}")
    clips = [
        clip
        for p in paths
        for clip in _load_clip_variants(p, rng, n_variants, center_on_speech)
    ]
    embeddings = features.embed_clips(np.stack(clips))
    # (n_clips, n_frames, emb_dim) -> average-pool frames into one vector per clip
    return embeddings.mean(axis=1)


def _embed_dirs(
    wav_dirs: "list[Path]",
    features: AudioFeatures,
    rng: np.random.Generator,
    user_variants: int,
    center_on_speech: bool = True,
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
        arrays.append(
            _embed_directory(wav_dir, features, rng, variants, center_on_speech)
        )
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
    # Negatives get windows sampled across the whole recording, including
    # onsets — see `_load_clip_variants`.
    neg = _embed_dirs(negative_dirs, features, rng, user_variants, center_on_speech=False)

    # Always present, whatever was recorded — see `_silence_and_noise_clips`.
    quiet = features.embed_clips(np.stack(_silence_and_noise_clips(rng))).mean(axis=1)
    neg = np.concatenate([neg, quiet])

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


def _default_dirs(candidates: "list[Path]") -> "list[Path]":
    """Keeps the conventional directories that actually exist and hold clips.

    Passing these by hand is the single most error-prone step of retraining —
    four long paths, and on Git Bash backslashes are silently eaten. They live
    at fixed locations, so the tool should just know them.
    """
    return [d for d in candidates if d.is_dir() and any(d.glob("*.wav"))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--positive-dir", type=Path, action="append",
        help="repeatable; a directory whose name contains 'user' is weighted "
             "higher. Defaults to the standard sample directories that exist.",
    )
    parser.add_argument("--negative-dir", type=Path, action="append")
    parser.add_argument("--out", type=Path, default=Path("data/wakeword/hey_peer.onnx"))
    args = parser.parse_args()

    positive_dirs = args.positive_dir or _default_dirs(DEFAULT_POSITIVE_DIRS)
    negative_dirs = args.negative_dir or _default_dirs(DEFAULT_NEGATIVE_DIRS)
    if not positive_dirs or not negative_dirs:
        raise SystemExit(
            "No training samples found. Record your voice first:\n"
            "  python -m heypeer.wakeword.record_samples"
        )

    for label, dirs in (("positive", positive_dirs), ("negative", negative_dirs)):
        for d in dirs:
            weight = "weighted" if "user" in d.name else "standard"
            print(f"  {label:8s} {d}  ({len(list(d.glob('*.wav')))} clips, {weight})")

    clf, input_dim = train(positive_dirs, negative_dirs)
    export_onnx(clf, input_dim, args.out)
    print(f"\nTrained classifier on {input_dim}-dim embeddings, exported to {args.out}")
    print("\nCheck it on your own voice with:")
    print("  python -m heypeer.wakeword.evaluate")


if __name__ == "__main__":
    main()
