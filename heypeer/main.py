"""Entry point wiring the full Hey Peer pipeline together for the demo scenario.

Flow: activity capture feeds a pattern detector, which stores newly detected
skills in memory. Once the wake word (or the tray's manual prompt) fires, the
user's instruction is sent to Nemotron along with the list of known skills and
the watched folder's current contents. Nemotron either resolves it to a known
skill, resolves it to a direct one-off file move (no skill needed - "deplace X
vers Y"), or reports it as unknown. Either way the user confirms before
anything executes.

Two independent PatternDetectors are used - one for generic input events
(clicks/keys/focus, from `ActivityWatcher`), one for file moves (from
`FileOpWatcher`) - so that incidental mouse activity during a drag-and-drop
can't spuriously "complete" a file-move pattern with the wrong actions, or
have a file move interrupt a click-sequence pattern.

The wake-word listener's `on_detected` callback fires from its own background
audio thread, which must stay cheap and non-blocking to keep reading the mic
smoothly. It only enqueues a signal onto `HeyPeer._detections` rather than
handling the instruction inline - blocking calls like `input()` were found to
not actually wait for keyboard input when called from that thread on Windows
(confirmed empirically: identical code worked fine called from the main
thread). Whichever thread drains that queue (the console loop in `run_cli`,
today) is where the actual instruction gathering happens.

By default this runs as a background app with a system tray icon (`TrayApp`).
Capture (learning skills from repeated action sequences / file moves) starts
natively as soon as the app launches - it's passive observation and nothing
ever executes from it without a separate, explicit confirmation, so there's no
real "off" state worth having for it. The "Mode auto" tray toggle and the
colored-cursor indicator are about something narrower: whether Hey Peer is
actually listening for the wake word and able to act on it. Pass `--cli` to
instead run the foreground console loop (useful for headless dev boxes, or for
watching the debug dB meter) - it also shows a real, detached tray icon so the
"Quitter" menu item works as a stop button instead of Task Manager.
"""

import argparse
import atexit
import queue
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

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
from heypeer.tray.debug_window import DebugWindow

GetInstruction = Callable[[], str]

_SHUTDOWN = object()  # sentinel put on HeyPeer._detections to unblock a consumer loop


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
        debug_window: DebugWindow | None = None,
    ) -> None:
        self.memory = memory
        self.wakeword_debug = wakeword_debug
        self.wakeword_threshold = wakeword_threshold
        self.debug_window = debug_window
        self.detector = detector
        # A separate detector for FILE_MOVE events - see module docstring for
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
        # Set once _run_wake_listener has either succeeded (entered its
        # blocking mic loop) or failed - lets callers wait for the *real*
        # outcome instead of guessing a fixed timeout. Loading the wake-word
        # model's two ONNX sessions + enumerating audio devices can easily
        # take more than a few hundred ms, so a short guessed timeout
        # previously reported "unavailable" while the listener was actually
        # still starting up successfully in the background.
        self._wake_ready = threading.Event()
        # Detections are enqueued here by the audio thread and drained by
        # whichever thread actually handles instructions (see module
        # docstring) - never handled inline in the audio callback.
        self._detections: queue.Queue = queue.Queue()

    def _log(self, message: str) -> None:
        print(message)
        if self.debug_window is not None:
            self.debug_window.log(message)

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
        act on it. Drives the cursor indicator too - capture/learning is
        unaffected, see `start_capture`."""
        self.cursor.set_active(enabled)
        if enabled:
            self._start_voice()
        else:
            self._stop_voice()

    def _start_voice(self) -> None:
        self._wake_ready.clear()
        self._wake_thread = threading.Thread(target=self._run_wake_listener, daemon=True)
        self._wake_thread.start()
        # Loading the Whisper model takes several seconds - warm it up now,
        # in parallel, rather than paying that cost on the user's first
        # spoken instruction. Doesn't block wake-word readiness.
        threading.Thread(target=self._preload_stt, daemon=True).start()
        threading.Thread(target=self._preload_tts, daemon=True).start()

    def _preload_stt(self) -> None:
        try:
            from heypeer.wakeword.stt import preload

            preload()
        except Exception as exc:
            print(f"[stt] Whisper preload failed (will retry on first use): {exc}")

    def _preload_tts(self) -> None:
        try:
            from heypeer.tray.tts import preload

            preload()
        except Exception as exc:
            print(f"[tts] Piper voice preload failed (will retry on first use): {exc}")

    def _speak(self, text: str) -> None:
        """Speaks `text` aloud (Piper TTS) — best-effort: a TTS failure
        (missing audio output device, voice download failure, ...) must
        never block the actual confirm/execute flow."""
        try:
            from heypeer.tray.tts import speak

            speak(text)
        except Exception as exc:
            print(f"[tts] Speak failed: {exc}")

    def _run_wake_listener(self) -> None:
        try:
            from heypeer.wakeword.listener import WakeWordListener, default_model_path

            model_path = default_model_path()
            if not model_path.exists():
                raise FileNotFoundError(model_path)
            self._wake_listener = WakeWordListener(
                str(model_path), threshold=self.wakeword_threshold, debug=self.wakeword_debug
            )
        except Exception as exc:
            # Deliberately broad: anything that goes wrong loading the model
            # or opening the mic (missing file, bad audio device, an
            # onnxruntime-internal error type that isn't an OSError subclass
            # -- this has actually happened) should degrade to this message
            # instead of an unhandled traceback in a background thread.
            print(
                f'Wake-word listener unavailable ({exc}). Mode auto actif mais '
                'sans activation vocale (utilise "Demander a Hey Peer..." dans '
                "le menu pour donner une instruction sans micro)."
            )
            self._wake_ready.set()
            return
        # Signal readiness *before* entering the blocking mic loop below,
        # which only returns once stop() is called.
        self._wake_ready.set()
        self._wake_listener.start(on_detected=self._on_wake_detected)

    def _on_wake_detected(self, audio: np.ndarray) -> None:
        """Called from the wake-word audio thread once a detection fires and
        the spoken instruction after it has already been recorded. Must stay
        cheap and non-blocking - see module docstring for why the actual
        instruction handling doesn't happen here."""
        self._detections.put(audio)

    def _stop_voice(self) -> None:
        if self._wake_listener is not None:
            self._wake_listener.stop()
            self._wake_listener = None
        self.cursor.reset()

    def _on_quit(self) -> None:
        self._stop_voice()
        self.stop_capture()
        self._detections.put(_SHUTDOWN)  # unblocks a consumer loop waiting on detections

    def _on_input_event(self, event: ActionEvent) -> None:
        skill = self.detector.observe(event)
        if skill is not None:
            self._log(f'Learned a new skill: "{skill.name}" ({skill.id})')
            self.memory.add(skill)
            self.memory.save()

    def _on_file_event(self, event: ActionEvent) -> None:
        skill = self.file_detector.observe(event)
        if skill is not None:
            self._log(f'Learned a new skill: "{skill.name}" ({skill.id})')
            self.memory.add(skill)
            self.memory.save()

    def _skill_context(self) -> list[dict]:
        return [{"id": s.id, "name": s.name} for s in self.memory.all()]

    def _watched_files(self) -> list[str] | None:
        if self.watched_dir is None or not self.watched_dir.is_dir():
            return None
        return sorted(p.name for p in self.watched_dir.iterdir() if p.is_file())

    def on_wake_word(self, audio: np.ndarray | None = None) -> None:
        """Handles one wake-word turn. If real recorded audio is given (the
        normal case once a mic is available), it's routed straight to
        Nemotron's omni `interpret()` - no separate speech-to-text step.
        Otherwise falls back to typed text via `get_instruction()` (manual
        Enter-key simulation, the tray prompt, tests). Must be called from a
        thread where blocking is safe - see module docstring."""
        self._log("Hey Peer detected.")
        try:
            if audio is not None and len(audio) > 0:
                intent = self._interpret_audio(audio)
            else:
                instruction_text = self.get_instruction()
                self._log(f"> {instruction_text}")
                intent = self.nemotron.interpret_text(
                    instruction_text, self._skill_context(), watched_files=self._watched_files()
                )
        except Exception as exc:
            self._log(f"Failed to interpret the instruction: {exc}")
            return
        self._dispatch_intent(intent)

    def _interpret_audio(self, audio: np.ndarray) -> Intent:
        """Transcribes the recorded instruction locally (Nemotron via this
        Nebius endpoint doesn't accept audio input - see
        heypeer/wakeword/stt.py and heypeer/nemotron/client.py's module
        docstrings for why) and sends the resulting text, plus a screenshot,
        to Nemotron for the actual reasoning."""
        import tempfile

        import pyautogui

        from heypeer.wakeword.stt import transcribe

        instruction_text = transcribe(audio)
        self._log(f"> {instruction_text}")
        if not instruction_text:
            return Intent(action="unknown", skill_id=None, n_repetitions=1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            screenshot_path = Path(tmp_dir) / "screenshot.png"
            pyautogui.screenshot().save(str(screenshot_path))
            return self.nemotron.interpret_text(
                instruction_text,
                self._skill_context(),
                watched_files=self._watched_files(),
                screenshot_path=str(screenshot_path),
            )

    def _handle_instruction(self, instruction_text: str) -> None:
        """Text-only path used by the tray's manual prompt and by tests."""
        intent = self.nemotron.interpret_text(
            instruction_text, self._skill_context(), watched_files=self._watched_files()
        )
        self._dispatch_intent(intent)

    def _dispatch_intent(self, intent: Intent) -> None:
        if intent.action == "run_skill" and intent.skill_id is not None:
            self._run_skill_intent(intent)
        elif intent.action == "move_file" and intent.src_filename and intent.dest_folder:
            self._run_move_file_intent(intent)
        else:
            self._log("Hey Peer didn't recognize a known skill or file action in that instruction.")

    def _run_skill_intent(self, intent: Intent) -> None:
        skill = self.memory.get(intent.skill_id)
        if skill is None:
            self._log(f"Nemotron referenced an unknown skill id: {intent.skill_id}")
            return

        times = f" {intent.n_repetitions} times" if intent.n_repetitions > 1 else ""
        self._speak(f"I'll {skill.name}{times}. Do you confirm?")
        if not confirm(intent, skill.name):
            self._log("Cancelled.")
            return

        runner = SkillRunner(
            verify_step=lambda png: self.nemotron.verify_screen(
                png, expected_context=f'next step of "{skill.name}"'
            )
        )
        self.tray.set_status(Status.EXECUTING)
        try:
            runner.run(skill, intent.n_repetitions)
            self._log(f'Done: "{skill.name}" x{intent.n_repetitions}.')
            self._speak("Done.")
        except ExecutionAborted as exc:
            self._log(f"Stopped mid-replay: {exc}")
            self._speak("I stopped partway through, something looked off.")
        finally:
            self.tray.set_status(Status.LISTENING if self.tray.auto_mode else Status.OFF)

    def _run_move_file_intent(self, intent: Intent) -> None:
        if self.watched_dir is None:
            self._log("No watched directory configured - can't resolve a direct file move.")
            return

        src_path = self.watched_dir / intent.src_filename
        # Kept inside the watched directory by design: Nemotron only ever
        # names a destination *folder name*, not an arbitrary path, so a
        # hallucinated or unexpected destination can't write outside it.
        dest_dir = self.watched_dir / intent.dest_folder

        description = f"move {intent.src_filename} -> {intent.dest_folder}/"
        self._speak(f"I'll move {intent.src_filename} into {intent.dest_folder}. Do you confirm?")
        if not confirm(intent, description):
            self._log("Cancelled.")
            return

        self.tray.set_status(Status.EXECUTING)
        try:
            new_path = move_single_file(src_path, dest_dir)
            self._log(f"Done: moved to {new_path}.")
            self._speak("Done.")
        except ExecutionAborted as exc:
            self._log(f"Stopped: {exc}")
            self._speak("I stopped, something looked off.")
        finally:
            self.tray.set_status(Status.LISTENING if self.tray.auto_mode else Status.OFF)


def _build_peer(with_debug_window: bool = False) -> HeyPeer:
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
        debug_window=DebugWindow() if with_debug_window else None,
    )


def run_tray() -> None:
    """Default entry point: a background app living in the system tray.

    Capture (skill learning) starts immediately - see `HeyPeer.start_capture`.
    "Mode auto" (wake-word listening + the colored-cursor indicator) is a
    simple ON/OFF toggle in the tray menu, and starts **ON** by default -
    turn it off from the menu if you don't want voice activation this
    session. `TrayApp.run()` blocks the calling thread with the tray's own
    event loop, so it must be called last, from the main thread.

    Note: on Windows, Ctrl+C in the console can't reliably interrupt the
    tray's native message loop - use the tray menu's "Quitter" to exit
    cleanly (it also resets the cursor).
    """
    peer = _build_peer(with_debug_window=True)
    atexit.register(peer.cursor.reset)
    peer.start_capture()
    peer.tray.set_auto_mode(True)
    print("Apprentissage de skills actif en arriere-plan.")
    print("Icone dans la zone de notification. Mode auto (ecoute vocale) : ON.")
    print('Menu "Demander a Hey Peer..." disponible pour tester sans micro.')

    # Wake-word detections still need a consumer thread even in tray mode -
    # see module docstring on why on_wake_word can't run on the audio thread.
    def _drain_detections() -> None:
        while True:
            item = peer._detections.get()
            if item is _SHUTDOWN:
                return
            peer.on_wake_word(item)

    threading.Thread(target=_drain_detections, daemon=True).start()
    peer.tray.run()


def run_cli() -> None:
    """Foreground console loop - no separate tray host process needed, but a
    real (detached) tray icon still runs alongside it so "Quitter" works as a
    stop button instead of Task Manager. Capture and voice/auto mode are both
    always on; Enter simulates the wake word if no trained wake-word model is
    available."""
    peer = _build_peer(with_debug_window=True)
    atexit.register(peer.cursor.reset)
    peer.start_capture()
    peer.tray.set_auto_mode(True)
    peer.tray.icon.run_detached()  # real tray icon, own thread - see Quitter note below

    try:
        # Waits for the *actual* outcome (success or failure) rather than a
        # guessed timeout - loading the wake-word model can legitimately take
        # a second or more. 15s is just a generous safety cap.
        peer._wake_ready.wait(timeout=15)
        if peer._wake_listener is None:
            print('Wake-word listener unavailable - press Enter to simulate "Hey Peer".')
            while True:
                input()
                peer.on_wake_word()
        else:
            # Detections are handled here, on the main thread, rather than
            # inline in the audio callback - input() did not actually wait
            # for keyboard input when called from that background thread on
            # Windows (confirmed: identical code worked fine on the main
            # thread). The tray's "Quitter" enqueues _SHUTDOWN to unblock
            # this loop cleanly instead of requiring Ctrl+C or Task Manager.
            print('Ecoute vocale active - Ctrl+C ou Quitter (icone) pour quitter.')
            while True:
                item = peer._detections.get()
                if item is _SHUTDOWN:
                    break
                peer.on_wake_word(item)
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
