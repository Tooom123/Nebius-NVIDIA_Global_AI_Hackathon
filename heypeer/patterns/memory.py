"""Local JSON-backed store for detected skills."""

import json
from pathlib import Path

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
            self._skills[entry["id"]] = Skill(
                id=entry["id"],
                name=entry["name"],
                actions=entry.get("actions", []),
                times_seen=entry.get("times_seen", 1),
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "id": skill.id,
                "name": skill.name,
                "actions": skill.actions,
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
