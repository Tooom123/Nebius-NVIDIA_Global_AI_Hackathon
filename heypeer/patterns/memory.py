"""Local JSON-backed store for detected skills."""

import json
from dataclasses import asdict
from pathlib import Path

from heypeer.capture.events import ActionEvent, ActionType
from heypeer.patterns.skill import Skill


class SkillMemory:
    """Loads/saves skills to a single JSON file. Sufficient for the demo scope."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._skills: dict[str, Skill] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text())
        for entry in raw:
            actions = [
                ActionEvent(
                    type=ActionType(a["type"]),
                    app_name=a["app_name"],
                    window_title=a["window_title"],
                    timestamp=a["timestamp"],
                    x=a.get("x"),
                    y=a.get("y"),
                    key_name=a.get("key_name"),
                    scroll_dx=a.get("scroll_dx"),
                    scroll_dy=a.get("scroll_dy"),
                )
                for a in entry.get("actions", [])
            ]
            self._skills[entry["id"]] = Skill(
                id=entry["id"],
                name=entry["name"],
                actions=actions,
                times_seen=entry.get("times_seen", 1),
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "id": skill.id,
                "name": skill.name,
                "actions": [asdict(a) for a in skill.actions],
                "times_seen": skill.times_seen,
            }
            for skill in self._skills.values()
        ]
        self.path.write_text(json.dumps(payload, indent=2))

    def add(self, skill: Skill) -> None:
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def all(self) -> list[Skill]:
        return list(self._skills.values())
