"""Client for Nemotron 3 Nano Omni served via Nebius Token Factory.

Nebius Token Factory exposes an OpenAI-compatible Chat Completions API, so this
uses the `openai` SDK pointed at Nebius's base URL.

`interpret_text` (optionally with a screenshot — `[text, image_url]` content,
confirmed working against the real endpoint) is the path actually used by the
running app. `interpret()` sends the full omni payload (audio clip +
screenshot + text) and is kept here, but nothing calls it: tested directly
against this Nebius deployment, every audio content-part shape tried
(`input_audio`, `audio_url`, `audio`) was rejected with an identical 422 the
moment the content list contains anything other than `text`/`image_url` —
there is no audio-input support on this endpoint today. Spoken instructions
are transcribed locally instead (see `heypeer/wakeword/stt.py`) and sent
through `interpret_text`, keeping the actual reasoning/intent step on
Nemotron while working around the missing audio input.
"""

import base64
import json
from pathlib import Path

from openai import OpenAI

from heypeer.config import Settings
from heypeer.nemotron.intent import Intent

VERIFY_SYSTEM_PROMPT = """\
You are Hey Peer, a personal automation assistant currently replaying a
learned skill step by step. You are given a screenshot of the current screen
and a short description of what the next action expects to see. Respond with
ONLY a JSON object: {"ok": <true or false>}. Use false if the screen doesn't
look like a state where the expected next action would make sense (e.g. an
unexpected dialog, a different app in focus, an error message).
"""

SYSTEM_PROMPT = """\
You are Hey Peer, a personal automation assistant. The user has just spoken a \
command after saying the wake word "Hey Peer". You are given: (1) the user's \
transcribed/spoken instruction, (2) a screenshot of their current screen, \
(3) a list of previously learned "skills" — repeated action sequences the user \
has performed before, each with an id and a human-readable name, and \
(4) optionally, the filenames currently present in the watched folder.

Decide what the user wants and respond with ONLY a JSON object of one of these
forms:

- To replay a learned skill:
  {"action": "run_skill", "skill_id": "<id from the list>", \
"n_repetitions": <integer, how many more times to run it, default 1>}

- To move/organize ONE specific file the user named directly (no repetition,
  no learned skill involved — e.g. "déplace le fichier facture vers Archives"):
  {"action": "move_file", \
"src_filename": "<the exact filename from the watched-folder listing that \
best matches what the user described>", \
"dest_folder": "<a short destination folder name, e.g. 'Archives' — an \
existing subfolder if one clearly matches, otherwise a new short name>"}
  Only use this when a specific single file and destination are named. Only
  pick src_filename from the filenames actually given to you — never invent
  one.

- If neither applies:
  {"action": "unknown"}

Always include every key shown for the chosen form; use null for any you
don't have a value for.
"""


def _skill_context_block(skill_context: list[dict]) -> str:
    return json.dumps(skill_context)


def _parse_intent(raw_content: str) -> Intent:
    data = json.loads(raw_content)
    return Intent(
        action=data["action"],
        skill_id=data.get("skill_id"),
        n_repetitions=int(data.get("n_repetitions") or 1),
        src_filename=data.get("src_filename"),
        dest_folder=data.get("dest_folder"),
    )


class NemotronClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = OpenAI(
            api_key=settings.nebius_api_key, base_url=settings.nebius_base_url
        )

    def interpret_text(
        self,
        instruction_text: str,
        skill_context: list[dict],
        watched_files: list[str] | None = None,
        screenshot_path: str | None = None,
    ) -> Intent:
        """The path actually used end to end: a transcribed instruction
        (locally, via `heypeer/wakeword/stt.py` — see module docstring for
        why not raw audio), optionally with a screenshot for visual context.
        A `[text, image_url]` content list is confirmed working against the
        real Nebius endpoint; plain-string content is used when no
        screenshot is given, keeping the original text-only path unchanged."""
        text = (
            f"Instruction: {instruction_text}\n"
            f"Known skills: {_skill_context_block(skill_context)}"
        )
        if watched_files is not None:
            text += f"\nFiles currently in the watched folder: {json.dumps(watched_files)}"

        if screenshot_path is None:
            content = text
        else:
            image_b64 = base64.b64encode(Path(screenshot_path).read_bytes()).decode()
            content = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]

        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
        )
        return _parse_intent(response.choices[0].message.content)

    def verify_screen(self, screenshot_png: bytes, expected_context: str) -> bool:
        """Visual verification hook used by SkillRunner between replay steps."""
        image_b64 = base64.b64encode(screenshot_png).decode()
        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Expected next action: {expected_context}"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return bool(data.get("ok", False))

    def interpret(
        self,
        audio_clip_path: str,
        screenshot_path: str,
        skill_context: list[dict],
        watched_files: list[str] | None = None,
    ) -> Intent:
        """Full omni path: audio clip + screenshot + skill list. Nemotron
        transcribes and reasons over the spoken instruction directly — no
        separate STT step."""
        audio_b64 = base64.b64encode(Path(audio_clip_path).read_bytes()).decode()
        image_b64 = base64.b64encode(Path(screenshot_path).read_bytes()).decode()
        files_block = (
            f"\nFiles currently in the watched folder: {json.dumps(watched_files)}"
            if watched_files is not None
            else ""
        )

        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Known skills: {_skill_context_block(skill_context)}"
                                f"{files_block}"
                            ),
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
