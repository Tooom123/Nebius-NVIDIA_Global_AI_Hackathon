"""Entry point wiring the full Hey Peer pipeline together for the demo scenario.

Flow: activity capture feeds a pattern detector, which stores newly detected
skills in memory. Once the wake word (or the tray's manual prompt) fires, the
user's instruction is sent to Nemotron along with the list of known skills and
the watched folder's current contents. Nemotron either resolves it to a known
skill, resolves it to a direct one-off file move (no skill needed — "déplace X
vers Y"), or reports it as unknown. Either way the user confirms before
anything executes.

Two independent PatternDetectors are used — one for generic input events
(clicks/keys/focus, from `ActivityWatcher`), one for file moves (from
`FileOpWatcher`) — so that incidental mouse activity during a drag-and-drop
can't spuriously "complete" a file-move pattern with the wrong actions, or
have a file move interrupt a click-sequence pattern.

By default this runs as a background app with a system tray icon (`TrayApp`).
Capture (learning skills from repeated action sequences / file moves) starts
natively as soon as the app launches — it's passive observation and nothing
ever executes from it without a separate, explicit confirmation, so there's no
real "off" state worth having for it. The "Mode auto" tray toggle and the
colored-cursor indicator are about something narrower: whether Hey Peer is
actually listening for the wake word and able to act on it. Pass `--cli` to
instead run the old foreground console loop, useful for headless dev boxes
without a tray host.
"""

import argparse
import atexit
import threading
from collections.abc import Callable
from pathlib import Path

from heypeer.capture.events import ActionEvent
from heypeer.capture.file_watcher import FileOpWatcher
from heypeer.capture.watcher import ActivityWatcher
from heypeer.config import SKILLS_DIR, load_settings
from heypeer.confirmation.cli import confirm
from heypeer.executor.runner import ExecutionAborted, SkillRunner, move_single_file
from heypeer.nemotron.client import NemotronClient
from heypeer.nemotron.intent import Intent
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
        file_detector: PatternDetector | None = None,
        wakeword_debug: bool = False,
        wakeword_threshold: float = 0.9,
    ) -> None:
        self.memory = memory
        self.wakeword_debug = wakeword_debug
        self.wakeword_threshold = wakeword_threshold
        self.detector = detector
        # A separate detector for FILE_MOVE events — see module docstring for
        # why generic input events and file moves must not share a buffer.
        self.file_detector = file_detector if file_detector is not None else PatternDetector()
        self.nemotron = nemotron
        self.get_instruction = get_instruction
        self.watched_dir = watched_dir
        self.watcher = ActivityWatcher(on_event=self._on_input_event)
        self.file_watcher = (
            FileOpWatcher(watched_dir, on_event=self._on_file_event)
            if watched_dir is not None
            else None
        )
        self.cursor = CursorIndicator()
        self.cursor.reset()  # clear any stale override left by a previous crashed run
        self.tray = TrayApp(
            on_auto_mode_change=self._set_auto_mode,
            on_quit=self._on_quit,
            on_prompt=self._handle_instruction,
        )
        self._wake_listener = None
        self._wake_thread: threading.Thread | None = None

    def start_capture(self) -> None:
        """Starts passive skill-learning capture (input events + file moves).
        Native/always-on: called once at app startup, independent of the
        "Mode auto" voice-activation toggle, since observation alone never
        executes anything without a separate confirmation."""
        self.watcher.start()
        if self.file_watcher is not None:
            self.file_watcher.start()

    def stop_capture(self) -> None:
        self.watcher.stop()
        if self.file_watcher is not None:
            self.file_watcher.stop()

    def _set_auto_mode(self, enabled: bool) -> None:
        """"Mode auto": is Hey Peer listening for the wake word and able to
        act on it. Drives the cursor indicator too — capture/learning is
        unaffected, see `start_capture`."""
        self.cursor.set_active(enabled)
        if enabled:
            self._start_voice()
        else:
            self._stop_voice()

    def _start_voice(self) -> None:
        self._wake_thread = threading.Thread(target=self._run_wake_listener, daemon=True)
        self._wake_thread.start()

    def _run_wake_listener(self) -> None:
        try:
            from heypeer.wakeword.listener import WakeWordListener, default_model_path

            model_path = default_model_path()
            if not model_path.exists():
                raise FileNotFoundError(model_path)
            self._wake_listener = WakeWordListener(
                str(model_path), threshold=self.wakeword_threshold, debug=self.wakeword_debug
            )
            self._wake_listener.start(on_detected=self.on_wake_word)
        except (FileNotFoundError, OSError) as exc:
            print(
                f'Wake-word listener unavailable ({exc}). Mode auto actif mais '
                'sans activation vocale (utilise "Demander à Hey Peer..." dans '
                "le menu pour donner une instruction sans micro)."
            )

    def _stop_voice(self) -> None:
        if self._wake_listener is not None:
            self._wake_listener.stop()
            self._wake_listener = None
        self.cursor.reset()

    def _on_quit(self) -> None:
        self._stop_voice()
        self.stop_capture()

    def _on_input_event(self, event: ActionEvent) -> None:
        skill = self.detector.observe(event)
        if skill is not None:
            print(f'Learned a new skill: "{skill.name}" ({skill.id})')
            self.memory.add(skill)
            self.memory.save()

    def _on_file_event(self, event: ActionEvent) -> None:
        skill = self.file_detector.observe(event)
        if skill is not None:
            print(f'Learned a new skill: "{skill.name}" ({skill.id})')
            self.memory.add(skill)
            self.memory.save()

    def _skill_context(self) -> list[dict]:
        return [{"id": s.id, "name": s.name} for s in self.memory.all()]

    def _watched_files(self) -> list[str] | None:
        if self.watched_dir is None or not self.watched_dir.is_dir():
            return None
        return sorted(p.name for p in self.watched_dir.iterdir() if p.is_file())

    def on_wake_word(self) -> None:
        """Called once "Hey Peer" is detected — gets the instruction (today:
        typed text, standing in for the transcribed audio clip) and handles it."""
        self._handle_instruction(self.get_instruction())

    def _handle_instruction(self, instruction_text: str) -> None:
        intent = self.nemotron.interpret_text(
            instruction_text, self._skill_context(), watched_files=self._watched_files()
        )

        if intent.action == "run_skill" and intent.skill_id is not None:
            self._run_skill_intent(intent)
        elif intent.action == "move_file" and intent.src_filename and intent.dest_folder:
            self._run_move_file_intent(intent)
        else:
            print("Hey Peer didn't recognize a known skill or file action in that instruction.")

    def _run_skill_intent(self, intent: Intent) -> None:
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

    def _run_move_file_intent(self, intent: Intent) -> None:
        if self.watched_dir is None:
            print("No watched directory configured — can't resolve a direct file move.")
            return

        src_path = self.watched_dir / intent.src_filename
        # Kept inside the watched directory by design: Nemotron only ever
        # names a destination *folder name*, not an arbitrary path, so a
        # hallucinated or unexpected destination can't write outside it.
        dest_dir = self.watched_dir / intent.dest_folder

        if not confirm(intent, f"move {intent.src_filename} -> {intent.dest_folder}/"):
            print("Cancelled.")
            return

        self.tray.set_status(Status.EXECUTING)
        try:
            new_path = move_single_file(src_path, dest_dir)
            print(f"Done: moved to {new_path}.")
        except ExecutionAborted as exc:
            print(f"Stopped: {exc}")
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
        wakeword_debug=settings.wakeword_debug,
        wakeword_threshold=settings.wakeword_threshold,
    )


def run_tray() -> None:
    """Default entry point: a background app living in the system tray.

    Capture (skill learning) starts immediately — see `HeyPeer.start_capture`.
    "Mode auto" (wake-word listening + the colored-cursor indicator) is a
    simple ON/OFF toggle in the tray menu, and starts **ON** by default —
    turn it off from the menu if you don't want voice activation this
    session. `TrayApp.run()` blocks the calling thread with the tray's own
    event loop, so it must be called last, from the main thread.

    Note: on Windows, Ctrl+C in the console can't reliably interrupt the
    tray's native message loop — use the tray menu's "Quitter" to exit
    cleanly (it also resets the cursor).
    """
    peer = _build_peer()
    atexit.register(peer.cursor.reset)
    peer.start_capture()
    peer.tray.set_auto_mode(True)
    print("Apprentissage de skills actif en arrière-plan.")
    print("Icône dans la zone de notification. Mode auto (écoute vocale) : ON.")
    print('Menu "Demander à Hey Peer..." disponible pour tester sans micro.')
    peer.tray.run()


def run_cli() -> None:
    """Foreground console loop — no tray/GUI needed, useful for headless dev
    boxes. Capture and voice/auto mode are both always on; Enter simulates
    the wake word if no trained wake-word model is available."""
    peer = _build_peer()
    atexit.register(peer.cursor.reset)
    peer.start_capture()
    peer.tray.set_auto_mode(True)

    try:
        if peer._wake_thread is not None:
            peer._wake_thread.join(timeout=0.5)
        if peer._wake_listener is None:
            print('Wake-word listener unavailable — press Enter to simulate "Hey Peer".')
            while True:
                input()
                peer.on_wake_word()
    finally:
        peer._on_quit()


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
