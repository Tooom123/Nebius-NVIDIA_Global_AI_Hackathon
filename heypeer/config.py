"""Shared configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
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
    )
