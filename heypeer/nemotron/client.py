"""Client for Nemotron 3 Nano Omni served via Nebius Token Factory.

Nebius Token Factory exposes an OpenAI-compatible Chat Completions API, so this
uses the `openai` SDK pointed at Nebius's base URL. Per the project plan, the
text-only path is meant to be validated first; `interpret_text` covers that.
`interpret` sends the full omni payload (audio clip + screenshot + text) once
that's ready to wire into the wake-word/capture pipeline.
"""

import base64
import json
from pathlib import Path

from openai import OpenAI

from heypeer.config import Settings
from heypeer.nemotron.intent import Intent

SYSTEM_PROMPT = """\
You are Hey Peer, a personal automation assistant. The user has just spoken a \
command after saying the wake word "Hey Peer". You are given: (1) the user's \
transcribed/spoken instruction, (2) a screenshot of their current screen, and \
(3) a list of previously learned "skills" — repeated action sequences the user \
has performed before, each with an id and a human-readable name.

Decide what the user wants and respond with ONLY a JSON object of the form:
{"action": "<one of: run_skill, unknown>", \
"skill_id": "<id of the matching skill from the list, or null>", \
"n_repetitions": <integer, how many more times to run it, default 1>}

If the instruction doesn't match any known skill, use "action": "unknown" and \
"skill_id": null.
"""


def _skill_context_block(skill_context: list[dict]) -> str:
    return json.dumps(skill_context)


def _parse_intent(raw_content: str) -> Intent:
    data = json.loads(raw_content)
    return Intent(
        action=data["action"],
        skill_id=data.get("skill_id"),
        n_repetitions=int(data.get("n_repetitions", 1)),
    )


class NemotronClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = OpenAI(
            api_key=settings.nebius_api_key, base_url=settings.nebius_base_url
        )

    def interpret_text(self, instruction_text: str, skill_context: list[dict]) -> Intent:
        """Text-only path — validates the prompt/skill-matching logic before
        wiring in real audio + screenshots."""
        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Instruction: {instruction_text}\n"
                        f"Known skills: {_skill_context_block(skill_context)}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        return _parse_intent(response.choices[0].message.content)

    def interpret(
        self, audio_clip_path: str, screenshot_path: str, skill_context: list[dict]
    ) -> Intent:
        """Full omni path: audio clip + screenshot + skill list."""
        audio_b64 = base64.b64encode(Path(audio_clip_path).read_bytes()).decode()
        image_b64 = base64.b64encode(Path(screenshot_path).read_bytes()).decode()

        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Known skills: {_skill_context_block(skill_context)}",
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_b64, "format": "wav"},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
        return _parse_intent(response.choices[0].message.content)
