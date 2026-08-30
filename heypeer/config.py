"""Shared configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SKILLS_DIR = DATA_DIR / "skills"
WAKEWORD_DIR = DATA_DIR / "wakeword"


@dataclass(frozen=True)
class Settings:
    nebius_api_key: str
    nebius_base_url: str
    nemotron_model_id: str
    watched_dir: Path = field(default_factory=lambda: Path.home() / "Downloads")
    # Off by default: "Hey Peer" has now been confirmed reliably triggering
    # on real hardware/voice (score 0.93-1.00 across multiple real
    # utterances), and the live per-chunk dB meter was making the console
    # noisy and hard to read alongside actual conversation output. Set
    # HEYPEER_WAKEWORD_DEBUG=1 to bring it back if a mic/hardware issue needs
    # diagnosing again.
    wakeword_debug: bool = False
    # 0.55 was a workaround for a model that couldn't discriminate: trained
    # on synthetic speech only, its false positives outscored many true ones,
    # so a loose threshold plus a strict second stage was the only workable
    # arrangement. A model personalised on the user's own voice separates the
    # classes properly — measured on their recordings, negatives sit at a
    # median of 0.17 against positives at 1.00 — so the threshold can do real
    # work again. 0.9 rather than 0.95 because those measurements are
    # optimistic (scored on the clips the model trained on), and a missed
    # activation costs the user a repeat while a false one is caught by the
    # verifier moments later. Raise it if false triggers persist.
    # Override with HEYPEER_WAKEWORD_THRESHOLD.
    wakeword_threshold: float = 0.9
    # Global mouse/keyboard capture (learning click/keystroke habits) is OFF
    # by default: the user reported it noticeably slowing their machine, and
    # the skills it learned from IDE/terminal activity were mostly noise
    # anyway. The per-keystroke `get_active_window()` call that caused most
    # of the cost is now throttled (see capture/watcher.py), but global input
    # hooks still have a real baseline cost, so this stays opt-in.
    # File-move capture (watchdog, cheap, and what the demo skill actually
    # uses) is unaffected and stays on.
    # Set HEYPEER_CAPTURE_INPUT=1 to re-enable.
    capture_input: bool = False
    # Skill learning (watching for repeated action sequences and storing them
    # as replayable "skills") is OFF by default. Hey Peer is voice-to-action
    # only for now, per an explicit product decision: the skills learned in
    # practice were near-useless ("Repeated sequence in unknown app"), every
    # one of them was sent to Nemotron on every request — bloating the prompt
    # badly once a couple of dozen had accumulated — and none of them ever
    # matched a spoken instruction. Set HEYPEER_LEARN_SKILLS=1 to re-enable.
    learn_skills: bool = False


def load_settings() -> Settings:
    return Settings(
        nebius_api_key=os.environ.get("NEBIUS_API_KEY", ""),
        nebius_base_url=os.environ.get(
            "NEBIUS_BASE_URL", "https://api.studio.nebius.ai/v1"
        ),
        nemotron_model_id=os.environ.get(
            "NEMOTRON_MODEL_ID", "nvidia/Nemotron-3-Nano-Omni"
        ),
        watched_dir=Path(os.environ.get("HEYPEER_WATCHED_DIR") or str(Path.home() / "Downloads")),
        wakeword_debug=(os.environ.get("HEYPEER_WAKEWORD_DEBUG") or "0") != "0",
        wakeword_threshold=float(os.environ.get("HEYPEER_WAKEWORD_THRESHOLD") or 0.9),
        capture_input=(os.environ.get("HEYPEER_CAPTURE_INPUT") or "0") != "0",
        learn_skills=(os.environ.get("HEYPEER_LEARN_SKILLS") or "0") != "0",
    )
