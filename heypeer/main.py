"""Entry point wiring the full Hey Peer pipeline together.

Each stage is implemented incrementally; running this before all stages are wired
will raise NotImplementedError for whichever stage hasn't landed yet.
"""

from heypeer.config import SKILLS_DIR, load_settings
from heypeer.patterns.detector import PatternDetector
from heypeer.patterns.memory import SkillMemory


def main() -> None:
    settings = load_settings()
    memory = SkillMemory(SKILLS_DIR / "skills.json")
    detector = PatternDetector()

    print(f"Hey Peer starting. {len(memory.all())} skill(s) in memory.")
    print(f"Nemotron model: {settings.nemotron_model_id}")
    print("Wake-word listener not wired yet — see heypeer/wakeword/listener.py")
    _ = detector


if __name__ == "__main__":
    main()
