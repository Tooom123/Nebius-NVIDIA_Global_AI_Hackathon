"""Records the user's own voice to personalise the "Hey Peer" wake word.

The shipped model was trained on synthetic Piper speech only — three English
voices, no real humans, no French accent. That is the root cause behind both
failure modes seen in real use: it fires on ordinary speech (what it really
learned to separate is "speech-like audio" from "noise", not this phrase
from other phrases) *and* it misses genuine activations. Everything built
around it since — the transcript verifier, the permissive threshold, the
follow-up window — works around that rather than fixing it.

Two recording sets, and the second matters as much as the first:

* **Positives** — the user saying "Hey Peer".
* **Negatives** — the *same voice* saying other things, including the
  commands they actually give ("déplace le fichier vers Archives") and
  near-misses ("Hey Pierre", "Hey Peter", "Hey", "Peer" alone).

Recording only positives would be the classic mistake: the model could then
separate the classes on voice identity alone — real human vs synthetic — and
would fire on anything the user says. Negatives in the same voice force it to
discriminate on *content*, which is the actual job. The command phrases are
there for a specific observed failure: the detector firing partway through an
instruction, right after the real wake word.

Usage:
    python -m heypeer.wakeword.record_samples
"""

import argparse
import time
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
CHUNK = 1024

# A wake word is short; a command is not. Recording windows sized to match.
POSITIVE_SECONDS = 2.0
NEGATIVE_SECONDS = 3.0

DEFAULT_POSITIVES = 40
COUNTDOWN_SECONDS = 1

POSITIVE_DIR = Path("data/wakeword/samples/positive_user")
NEGATIVE_DIR = Path("data/wakeword/samples/negative_user")

# Anything peaking below this is almost certainly a missed take (spoke too
# late, mic muted) and would teach the model that silence is a wake word.
MIN_PEAK = 0.02

# Deliberately three kinds of negative, all in the user's own voice:
# near-misses that share most of the phrase's sound, the real commands that
# follow a wake word (the detector was observed firing partway through one),
# and ordinary speech.
NEGATIVE_PROMPTS = [
    # Near-misses — the hardest and most valuable negatives.
    "Hey Pierre",
    "Hey Peter",
    "Hey Paul",
    "Hé, pardon",
    "Peer",
    "Hey",
    "Hey, ça va ?",
    "Hey les gars",
    "peur",
    "père",
    # Real commands, said without the wake word in front.
    "déplace le fichier facture vers Archives",
    "renomme le fichier 4 en 15",
    "crée un dossier Factures",
    "supprime le fichier notes point txt",
    "déplace le fichier 6 dans le dossier test",
    "annule",
    "crée un fichier notes point txt",
    "déplace les photos dans le dossier vacances",
    # Ordinary speech.
    "je ne sais pas trop quoi en penser",
    "il faut que je rappelle demain matin",
    "on se retrouve à quelle heure",
    "j'ai presque fini ce que je faisais",
    "attends deux secondes s'il te plaît",
    "c'est exactement ce que je voulais dire",
    "tu peux répéter la dernière phrase",
    "je vais prendre un café",
]


def record_clip(stream, seconds: float) -> np.ndarray:
    """Reads `seconds` of int16 mono audio from an open stream."""
    frames = []
    for _ in range(int(SAMPLE_RATE * seconds / CHUNK)):
        raw = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(np.frombuffer(raw, dtype=np.int16))
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)


def clip_peak(clip: np.ndarray) -> float:
    """Peak amplitude as a 0-1 fraction of full scale."""
    if len(clip) == 0:
        return 0.0
    return float(np.abs(clip).max()) / 32768.0


def is_usable(clip: np.ndarray) -> bool:
    """Whether a take actually contains something. A silent clip saved as a
    positive would teach the model that silence is the wake word, which is
    worse than simply having one fewer sample."""
    return clip_peak(clip) >= MIN_PEAK


def _countdown(label: str) -> None:
    print(f"\n{label}")
    for remaining in range(COUNTDOWN_SECONDS, 0, -1):
        print(f"  {remaining}...", end="\r", flush=True)
        time.sleep(1)
    print("  >>> PARLE MAINTENANT        ", end="\r", flush=True)


def _save(clip: np.ndarray, directory: Path, index: int, prefix: str) -> Path:
    from heypeer.wakeword.listener import save_wav

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}_{index:03d}.wav"
    save_wav(clip, path)
    return path


def record_set(
    stream, directory: Path, prompts: "list[str]", seconds: float, prefix: str
) -> int:
    """Records one take per prompt, retrying a prompt whose take was silent.
    Returns how many clips were saved."""
    saved = 0
    for index, prompt in enumerate(prompts):
        while True:
            _countdown(f'[{index + 1}/{len(prompts)}]  Dis : "{prompt}"')
            clip = record_clip(stream, seconds)
            if is_usable(clip):
                path = _save(clip, directory, index, prefix)
                print(f"  enregistre -> {path.name} (pic {clip_peak(clip):.0%})   ")
                saved += 1
                break
            print("  rien entendu, on refait celui-la.                ")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--positives", type=int, default=DEFAULT_POSITIVES,
        help="how many times to say the wake word",
    )
    parser.add_argument("--positive-dir", type=Path, default=POSITIVE_DIR)
    parser.add_argument("--negative-dir", type=Path, default=NEGATIVE_DIR)
    args = parser.parse_args()

    import pyaudio

    print("=" * 62)
    print("Enregistrement de ta voix pour personnaliser le mot d'activation")
    print("=" * 62)
    print()
    print("Deux series :")
    print(f"  1. {args.positives} fois \"Hey Peer\"")
    print(f"  2. {len(NEGATIVE_PROMPTS)} autres phrases (pour lui apprendre a NE PAS")
    print("     se declencher dessus - c'est aussi important que la serie 1)")
    print()
    print("Conseils : parle normalement, comme tu le ferais en vrai. Varie")
    print("un peu le ton, la vitesse et la distance au micro entre les prises,")
    print("et enregistre dans l'endroit ou tu utilises Hey Peer.")
    print()
    input("Appuie sur Entree quand tu es pret... ")

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
        input=True, frames_per_buffer=CHUNK,
    )
    try:
        print("\n--- Serie 1/2 : le mot d'activation ---")
        n_pos = record_set(
            stream, args.positive_dir, ["Hey Peer"] * args.positives,
            POSITIVE_SECONDS, "pos",
        )

        print("\n--- Serie 2/2 : ce qui ne doit PAS declencher ---")
        n_neg = record_set(
            stream, args.negative_dir, NEGATIVE_PROMPTS, NEGATIVE_SECONDS, "neg"
        )
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

    print(f"\n{n_pos} positifs -> {args.positive_dir}")
    print(f"{n_neg} negatifs -> {args.negative_dir}")
    print("\nEntraine maintenant le modele avec :")
    print("  python -m heypeer.wakeword.train \\")
    print(f"      --positive-dir {args.positive_dir} \\")
    print("      --positive-dir data/wakeword/samples/positive_augmented \\")
    print(f"      --negative-dir {args.negative_dir} \\")
    print("      --negative-dir data/wakeword/samples/negative_noise")


if __name__ == "__main__":
    main()
