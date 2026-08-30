"""Measures how a trained wake-word model behaves on real clips.

Held-out clip accuracy is not enough, and this project has the scars to prove
it: an earlier model scored 96% on held-out clips while being broken in two
distinct ways that only a *streaming* evaluation exposed (it had learned clip
alignment rather than the word, and had leaked voice identity). So this feeds
each clip through `AudioFeatures` chunk by chunk, exactly as
`listener.py` does at runtime, and scores the rolling window the same way —
the peak score over the clip is what the live listener would actually see.

Reports recall and false-accept rate across candidate thresholds, so the
shipped threshold is chosen from measurements rather than taste.

Usage:
    python -m heypeer.wakeword.evaluate \\
        --model data/wakeword/hey_peer.onnx \\
        --positive-dir data/wakeword/samples/positive_user \\
        --negative-dir data/wakeword/samples/negative_user
"""

import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
from openwakeword.utils import AudioFeatures

from heypeer.wakeword.listener import CHUNK_SAMPLES, CLIP_SECONDS, SAMPLE_RATE

THRESHOLDS = (0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 0.95)


def peak_score(path: Path, session, features: AudioFeatures, n_frames: int) -> float:
    """Highest score the live listener would reach anywhere in this clip.

    Streaming, not one-shot: the runtime feeds a continuously sliding buffer
    and fires the moment any window crosses the threshold, so the peak over
    the clip — not a score for the clip as a whole — is what decides whether
    it triggers.
    """
    audio, sr = sf.read(str(path), dtype="int16", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype("int16")
    if sr != SAMPLE_RATE:
        raise ValueError(f"{path} is {sr} Hz, expected {SAMPLE_RATE} Hz")

    # Lead-in silence so the rolling buffer starts empty, as it does live.
    padded = np.concatenate([np.zeros(int(CLIP_SECONDS * SAMPLE_RATE), dtype=np.int16), audio])

    input_name = session.get_inputs()[0].name
    best = 0.0
    for start in range(0, len(padded) - CHUNK_SAMPLES + 1, CHUNK_SAMPLES):
        features(padded[start : start + CHUNK_SAMPLES])
        embedding = features.get_features(n_feature_frames=n_frames).mean(axis=1)
        probs = session.run(None, {input_name: embedding.astype(np.float32)})[1]
        best = max(best, float(probs[0][1]))
    return best


def score_directory(wav_dir: Path, session, n_frames: int) -> "list[float]":
    """Peak score per clip. A fresh `AudioFeatures` per clip keeps one clip's
    audio from bleeding into the next through the rolling buffer."""
    scores = []
    for path in sorted(wav_dir.glob("*.wav")):
        scores.append(peak_score(path, session, AudioFeatures(), n_frames))
    return scores


def report(positive_scores: "list[float]", negative_scores: "list[float]") -> None:
    pos = np.asarray(positive_scores)
    neg = np.asarray(negative_scores)
    print(f"\n{len(pos)} positive clip(s), {len(neg)} negative clip(s)\n")
    print(f"{'threshold':>10}  {'recall':>8}  {'false accepts':>14}")
    print("-" * 36)
    for threshold in THRESHOLDS:
        recall = float((pos >= threshold).mean()) if len(pos) else 0.0
        far = float((neg >= threshold).mean()) if len(neg) else 0.0
        print(f"{threshold:>10.2f}  {recall:>7.0%}  {far:>13.0%}")

    if len(pos) and len(neg):
        print(
            f"\npositives: min {pos.min():.2f}  median {np.median(pos):.2f}"
            f"\nnegatives: max {neg.max():.2f}  median {np.median(neg):.2f}"
        )
        # The useful question is whether the two distributions separate at
        # all. If the worst positive scores below the best negative, no
        # threshold can split them and the model needs more/better data —
        # which is exactly the state the synthetic-only model was in.
        if pos.min() > neg.max():
            print(
                f"\nCleanly separable: any threshold between {neg.max():.2f} and "
                f"{pos.min():.2f} gets 100% recall with no false accepts."
            )
        else:
            print(
                "\nThe distributions overlap — no threshold separates them "
                "perfectly. Pick from the table above, or record more samples "
                "(especially negatives that sound close to the wake word)."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("data/wakeword/hey_peer.onnx"))
    parser.add_argument("--positive-dir", type=Path, required=True, action="append")
    parser.add_argument("--negative-dir", type=Path, required=True, action="append")
    args = parser.parse_args()

    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    n_frames = AudioFeatures().get_embedding_shape(CLIP_SECONDS)[0]

    positives = [s for d in args.positive_dir for s in score_directory(d, session, n_frames)]
    negatives = [s for d in args.negative_dir for s in score_directory(d, session, n_frames)]
    report(positives, negatives)


if __name__ == "__main__":
    main()
