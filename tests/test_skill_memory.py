from pathlib import Path

from heypeer.patterns.memory import SkillMemory
from heypeer.patterns.skill import Skill


def test_add_and_persist(tmp_path: Path) -> None:
    store_path = tmp_path / "skills.json"
    memory = SkillMemory(store_path)
    memory.add(Skill(id="sort_files", name="Sort downloaded files"))
    memory.save()

    reloaded = SkillMemory(store_path)
    skill = reloaded.get("sort_files")
    assert skill is not None
    assert skill.name == "Sort downloaded files"
