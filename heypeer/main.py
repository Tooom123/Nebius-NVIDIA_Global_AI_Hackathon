"""Entry point wiring the full Hey Peer pipeline together for the demo scenario.

Flow: activity capture feeds the pattern detector, which stores newly detected
skills in memory. Once the wake word fires, the user's instruction (today: typed
text, standing in for the transcribed audio clip until the full omni audio path
is exercised against a live Nebius endpoint) is sent to Nemotron along with the
list of known skills. If it resolves to a known skill, the user confirms before
SkillRunner replays it, with Nemotron re-checking the screen between steps.
"""

from collections.abc import Callable
from pathlib import Path

from heypeer.capture.events import ActionEvent
from heypeer.capture.file_watcher import FileOpWatcher
from heypeer.capture.watcher import ActivityWatcher
from heypeer.config import SKILLS_DIR, load_settings
from heypeer.confirmation.cli import confirm
from heypeer.executor.runner import ExecutionAborted, SkillRunner
from heypeer.nemotron.client import NemotronClient
from heypeer.patterns.detector import PatternDetector
from heypeer.patterns.memory import SkillMemory

GetInstruction = Callable[[], str]


def _default_get_instruction() -> str:
    return input("Hey Peer heard you. What do you want to do? ")


class HeyPeer:
    """Wires capture -> detection -> interpretation -> confirmation -> execution.

    Split out as a class (rather than one long function) so each stage can be
    exercised independently in tests via constructor injection.
    """

    def __init__(
        self,
        memory: SkillMemory,
        detector: PatternDetector,
        nemotron: NemotronClient,
        watched_dir: Path | None = None,
        get_instruction: GetInstruction = _default_get_instruction,
    ) -> None:
        self.memory = memory
        self.detector = detector
        self.nemotron = nemotron
        self.get_instruction = get_instruction
        self.watcher = ActivityWatcher(on_event=self._on_capture_event)
        self.file_watcher = (
            FileOpWatcher(watched_dir, on_event=self._on_capture_event)
            if watched_dir is not None
            else None
        )

    def _on_capture_event(self, event: ActionEvent) -> None:
        skill = self.detector.observe(event)
        if skill is not None:
            print(f'Learned a new skill: "{skill.name}" ({skill.id})')
            self.memory.add(skill)
            self.memory.save()

    def _skill_context(self) -> list[dict]:
        return [{"id": s.id, "name": s.name} for s in self.memory.all()]

    def on_wake_word(self) -> None:
        """Called once "Hey Peer" is detected. Handles the rest of the turn."""
        instruction_text = self.get_instruction()
        intent = self.nemotron.interpret_text(instruction_text, self._skill_context())

        if intent.action != "run_skill" or intent.skill_id is None:
            print("Hey Peer didn't recognize a known skill in that instruction.")
            return

        skill = self.memory.get(intent.skill_id)
        if skill is None:
            print(f"Nemotron referenced an unknown skill id: {intent.skill_id}")
            return

        if not confirm(intent, skill.name):
            print("Cancelled.")
            return

        runner = SkillRunner(
            verify_step=lambda png: self.nemotron.verify_screen(
                png, expected_context=f'next step of "{skill.name}"'
            )
        )
        try:
            runner.run(skill, intent.n_repetitions)
            print(f'Done: "{skill.name}" x{intent.n_repetitions}.')
        except ExecutionAborted as exc:
            print(f"Stopped mid-replay: {exc}")


def main() -> None:
    settings = load_settings()
    memory = SkillMemory(SKILLS_DIR / "skills.json")
    peer = HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=NemotronClient(settings),
        watched_dir=settings.watched_dir,
    )

    print(f"Hey Peer starting. {len(memory.all())} skill(s) in memory.")
    print(f"Nemotron model: {settings.nemotron_model_id}")
    print(f"Watching for file moves in: {settings.watched_dir}")
    peer.watcher.start()
    if peer.file_watcher is not None:
        peer.file_watcher.start()

    try:
        from heypeer.wakeword.listener import WakeWordListener, default_model_path

        model_path = default_model_path()
        if not model_path.exists():
            raise FileNotFoundError(model_path)
        listener = WakeWordListener(str(model_path))
        print('Listening for "Hey Peer"...')
        listener.start(on_detected=peer.on_wake_word)
    except (FileNotFoundError, OSError) as exc:
        print(f"Wake-word listener unavailable ({exc}).")
        print('Falling back to manual activation: press Enter to simulate "Hey Peer".')
        while True:
            input()
            peer.on_wake_word()
    finally:
        peer.watcher.stop()
        if peer.file_watcher is not None:
            peer.file_watcher.stop()


if __name__ == "__main__":
    main()
