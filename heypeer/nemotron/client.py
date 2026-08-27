"""Client for Nemotron 3 Nano Omni served via Nebius Token Factory.

Wiring of the actual audio+vision+text request lands in a later step (first
validated with text-only prompts per the project plan); this module defines the
interface consumed by the rest of the pipeline.
"""

from heypeer.config import Settings
from heypeer.nemotron.intent import Intent


class NemotronClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def interpret(
        self, audio_clip_path: str, screenshot_path: str, skill_context: list[dict]
    ) -> Intent:
        raise NotImplementedError("Nemotron interpretation call not implemented yet")
