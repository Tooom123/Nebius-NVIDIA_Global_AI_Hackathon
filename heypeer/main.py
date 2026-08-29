"""Entry point wiring the full Hey Peer pipeline together for the demo scenario.

Flow: activity capture feeds the pattern detector, which stores newly detected
skills in memory. Once the wake word fires, the user's instruction (today: typed
text, standing in for the transcribed audio clip until the full omni audio path
is exercised against a live Nebius endpoint) is sent to Nemotron along with the
list of known skills. If it resolves to a known skill, the user confirms before
SkillRunner replays it, with Nemotron re-checking the screen between steps.

By default this runs as a background app with a system tray icon (`TrayApp`):
the "Mode auto" menu toggle arms/disarms the whole pipeline (capture watchers +
wake-word listener) and drives the colored-cursor indicator (`CursorIndicator`).
Pass `--cli` to instead run the old foreground console loop, useful for
headless dev boxes without a tray host.
"""

import argparse
import threading
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
from heypeer.tray.app import Status, TrayApp
from heypeer.tray.cursor import CursorIndicator

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
        self.watched_dir = watched_dir
        self.watcher = ActivityWatcher(on_event=self._on_capture_event)
        self.file_watcher = (
            FileOpWatcher(watched_dir, on_event=self._on_capture_event)
            if watched_dir is not None
            else None
        )
        self.cursor = CursorIndicator()
        self.tray = TrayApp(on_auto_mode_change=self._set_auto_mode, on_quit=self._stop_pipeline)
        self._wake_listener = None
        self._wake_thread: threading.Thread | None = None

    def _set_auto_mode(self, enabled: bool) -> None:
        self.cursor.set_active(enabled)
        if enabled:
            self._start_pipeline()
        else:
            self._stop_pipeline()

    def _start_pipeline(self) -> None:
        self.watcher.start()
        if self.file_watcher is not None:
            self.file_watcher.start()
        self._wake_thread = threading.Thread(target=self._run_wake_listener, daemon=True)
        self._wake_thread.start()

    def _run_wake_listener(self) -> None:
        try:
            from heypeer.wakeword.listener import WakeWordListener, default_model_path

            model_path = default_model_path()
            if not model_path.exists():
                raise FileNotFoundError(model_path)
            self._wake_listener = WakeWordListener(str(model_path))
            self._wake_listener.start(on_detected=self.on_wake_word)
        except (FileNotFoundError, OSError) as exc:
            print(
                f'Wake-word listener unavailable ({exc}). Mode auto actif '
                "mais sans activation vocale — le tri de fichiers reste surveillé."
            )

    def _stop_pipeline(self) -> None:
        self.watcher.stop()
        if self.file_watcher is not None:
            self.file_watcher.stop()
        if self._wake_listener is not None:
            self._wake_listener.stop()
            self._wake_listener = None

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
        self.tray.set_status(Status.EXECUTING)
        try:
            runner.run(skill, intent.n_repetitions)
            print(f'Done: "{skill.name}" x{intent.n_repetitions}.')
        except ExecutionAborted as exc:
            print(f"Stopped mid-replay: {exc}")
        finally:
            self.tray.set_status(Status.LISTENING if self.tray.auto_mode else Status.OFF)


def _build_peer() -> HeyPeer:
    settings = load_settings()
    memory = SkillMemory(SKILLS_DIR / "skills.json")
    print(f"Hey Peer starting. {len(memory.all())} skill(s) in memory.")
    print(f"Nemotron model: {settings.nemotron_model_id}")
    print(f"Watching for file moves in: {settings.watched_dir}")
    return HeyPeer(
        memory=memory,
        detector=PatternDetector(),
        nemotron=NemotronClient(settings),
        watched_dir=settings.watched_dir,
    )


def run_tray() -> None:
    """Default entry point: a background app living in the system tray.

    "Mode auto" in the tray menu arms/disarms capture + wake-word listening
    and the colored-cursor indicator. `TrayApp.run()` blocks the calling
    thread with the tray's own event loop, so it must be called last, from
    the main thread.
    """
    peer = _build_peer()
    print("Icône dans la zone de notification. Active « Mode auto » pour démarrer.")
    peer.tray.run()


def run_cli() -> None:
    """Foreground console loop — no tray/GUI needed, useful for headless dev
    boxes. Auto mode is always on; Enter simulates the wake word if no
    trained wake-word model is available."""
    peer = _build_peer()
    peer._set_auto_mode(True)

    try:
        if peer._wake_thread is not None:
            peer._wake_thread.join(timeout=0.5)
        if peer._wake_listener is None:
            print('Wake-word listener unavailable — press Enter to simulate "Hey Peer".')
            while True:
                input()
                peer.on_wake_word()
    finally:
        peer._stop_pipeline()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run the foreground console loop instead of the system tray app",
    )
    args = parser.parse_args()
    run_cli() if args.cli else run_tray()


if __name__ == "__main__":
    main()
