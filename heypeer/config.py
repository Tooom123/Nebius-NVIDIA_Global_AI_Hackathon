"""Shared configuration loaded from environment variables."""

import os
from dataclasses import dataclass
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


def load_settings() -> Settings:
    return Settings(
        nebius_api_key=os.environ.get("NEBIUS_API_KEY", ""),
        nebius_base_url=os.environ.get(
            "NEBIUS_BASE_URL", "https://api.studio.nebius.ai/v1"
        ),
        nemotron_model_id=os.environ.get(
            "NEMOTRON_MODEL_ID", "nvidia/nemotron-3-nano-omni"
        ),
    )
