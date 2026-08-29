"""Entry point wiring the full Hey Peer pipeline together for the demo scenario.

Flow: activity capture feeds a pattern detector, which stores newly detected
skills in memory. Once the wake word (or the tray's manual prompt) fires, the
user's instruction is sent to Nemotron along with the list of known skills and
the watched folder's current contents. Nemotron either resolves it to a known
skill, resolves it to a direct one-off file action - move/rename/create/
delete (no skill needed - "deplace X vers Y", "renomme X en Y", ...) - or
reports it as unknown. There used to be a confirmation step before executing
anything; removed per explicit user feedback that it caused more problems
than it solved (voice replies were often misheard and defaulted to "no",
blocking real actions). Hey Peer still narrates what it's about to do out
loud before doing it, just doesn't wait for a reply any more.

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
natively as soon as the app launches - it's passive observation on its own
(nothing runs until the wake word actually resolves to an action), so there's
no real "off" state worth having for it. The "Mode auto" tray toggle and the
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
from heypeer.executor.runner import (
    ExecutionAborted,
    SkillRunner,
    create_file,
    create_folder,
    delete_file,
    move_single_file,
    rename_file,
)
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


# Values Nemotron returns to mean "I couldn't determine this" — they must
# never be taken literally as a file/folder name (see `_has_placeholder_name`).
_PLACEHOLDER_NAMES = {"unknown", "none", "null", "n/a", "undefined", "inconnu", ""}

# Screenshot sent to Nemotron as visual context. Long edge in pixels and JPEG
# quality — see `_interpret_audio` for why this isn't a full-resolution PNG.
SCREENSHOT_MAX_PX = 768
SCREENSHOT_QUALITY = 60


def _has_placeholder_name(intent: Intent) -> bool:
    """Whether any name field on `intent` is a stand-in for "not determined"
    rather than a real name the user asked for."""
    names = (intent.src_filename, intent.dest_folder, intent.new_name, intent.target_name)
    return any(name is not None and name.strip().lower() in _PLACEHOLDER_NAMES for name in names)


class HeyPeer:
    """Wires capture -> detection -> interpretation -> execution.

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
        capture_input: bool = False,
    ) -> None:
        self.memory = memory
        self.wakeword_debug = wakeword_debug
        self.wakeword_threshold = wakeword_threshold
        self.capture_input = capture_input
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
        """The conversation lives in the terminal now - the debug window is
        just the visual state/level indicator (see `debug_window.py`)."""
        print(message)

    def start_capture(self) -> None:
        """Starts passive skill-learning capture (input events + file moves).
        Native/always-on: called once at app startup, independent of the
        "Mode auto" voice-activation toggle - observation alone never
        executes anything on its own, only a resolved wake-word intent does.

        Input capture (mouse/keyboard habits) is opt-in via
        `HEYPEER_CAPTURE_INPUT` - see `Settings.capture_input` for why it's
        off by default. File-move capture is always on: it's cheap and it's
        what the demo skill actually learns from."""
        if self.capture_input:
            self.watcher.start()
        if self.file_watcher is not None:
            self.file_watcher.start()

    def stop_capture(self) -> None:
        if self.capture_input:
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
        never block the actual execution flow. Muting the wake-word listener
        happens for the whole turn now (see `_on_wake_detected`/
        `on_wake_word`), not just here, so this no longer needs to touch it
        itself — kept as a no-op-safe method regardless."""
        if self.debug_window is not None:
            self.debug_window.set_state("speaking")
        try:
            from heypeer.tray.tts import speak

            speak(text)
        except Exception as exc:
            print(f"[tts] Speak failed: {exc}")
        finally:
            if self.debug_window is not None:
                self.debug_window.set_state("listening")

    def _speak_async(self, text: str) -> None:
        """Speaks without blocking the caller. Used for narration that
        precedes an action: the action shouldn't wait for a whole sentence
        of speech to play before it happens."""
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _on_audio_level(self, level: float, recording: bool) -> None:
        """Forwards the live mic level to the indicator's audio-reactive blob.

        Deliberately does *not* set the state: recording begins before
        verification has confirmed the wake word (they run concurrently), so
        flipping to a visible state here would pop the blob up for every
        false trigger. `_verify_wake_word` owns that transition instead."""
        if self.debug_window is None or not recording:
            return
        self.debug_window.set_level(level)

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
        if self.debug_window is not None:
            self.debug_window.set_state("listening")
        self._wake_listener.start(
            on_detected=self._on_wake_detected,
            on_level=self._on_audio_level,
            on_verify=self._verify_wake_word,
        )

    def _verify_wake_word(self, pre_trigger_audio: np.ndarray) -> bool:
        """Confirms a detection really was "Hey Peer", from the audio around
        the trigger, and only *then* produces any user-visible reaction.

        This is where the chime and the on-screen indicator fire, deliberately
        — the raw detector fires on plenty of ordinary speech (it was trained
        on synthetic voices only), so chiming or showing the blob on the raw
        trigger surfaced every false positive to the user. Runs on its own
        thread while the instruction is still being recorded, so confirmation
        still lands within a few hundred ms of the wake word."""
        try:
            from heypeer.wakeword.stt import transcribe
            from heypeer.wakeword.verify import contains_wake_word

            if not contains_wake_word(transcribe(pre_trigger_audio)):
                return False
        except Exception as exc:
            # Never lose a genuine activation to a verification failure —
            # a missing model or a transcription error shouldn't make Hey
            # Peer deaf. Falls back to trusting the detector.
            print(f"[wakeword] Verification failed, accepting the trigger: {exc}")
            return True

        from heypeer.wakeword.listener import play_activation_chime

        try:
            play_activation_chime()
        except Exception as exc:  # best-effort - never block on a beep
            print(f"[wakeword] Chime playback failed: {exc}")
        if self.debug_window is not None:
            self.debug_window.set_state("recording")
        return True

    def _on_wake_detected(self, audio: np.ndarray) -> None:
        """Called from the wake-word audio thread once a detection fires and
        the spoken instruction after it has already been recorded. Must stay
        cheap and non-blocking - see module docstring for why the actual
        instruction handling doesn't happen here.

        Mutes the listener immediately, before even enqueueing - real
        wake-word logs showed the audio thread picking up a *second*
        "Hey Peer" (or just ambient chatter scoring above threshold) while
        the first instruction was still being transcribed/interpreted, since
        muting previously only covered the brief TTS-playback window. Hey
        Peer now handles one turn fully (transcribe -> interpret -> execute
        -> speak) before listening for another wake word at all - unmuted at
        the very end of `on_wake_word`/`_handle_instruction`, whichever way
        the turn ends."""
        if self._wake_listener is not None:
            self._wake_listener.mute()
        self._detections.put(audio)

    def _stop_voice(self) -> None:
        if self._wake_listener is not None:
            self._wake_listener.stop()
            self._wake_listener = None
        self.cursor.reset()
        if self.debug_window is not None:
            self.debug_window.set_state("idle")

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

    def _watched_folders(self) -> list[str] | None:
        """Existing subfolders of the watched directory - given to Nemotron
        so it can reuse a real folder instead of inventing a plausible-but-
        wrong variant of a name the user said (a real bug: "test" ->
        created "tests", since Nemotron had no listing to check against)."""
        if self.watched_dir is None or not self.watched_dir.is_dir():
            return None
        return sorted(p.name for p in self.watched_dir.iterdir() if p.is_dir())

    def on_wake_word(self, audio: np.ndarray | None = None) -> None:
        """Handles one wake-word turn. If real recorded audio is given (the
        normal case once a mic is available), it's transcribed locally then
        sent to Nemotron (see `_interpret_audio` for why not native audio
        input). Otherwise falls back to typed text via `get_instruction()`
        (manual Enter-key simulation, the tray prompt, tests). Must be
        called from a thread where blocking is safe - see module docstring.

        The wake-word listener stays muted (see `_on_wake_detected`) for the
        whole turn - unmuted here in a `finally`, once fully done, however
        the turn ends, so Hey Peer only ever handles one turn at a time."""
        if self.debug_window is not None:
            self.debug_window.set_state("thinking")
        try:
            try:
                if audio is not None and len(audio) > 0:
                    intent = self._interpret_audio(audio)
                    if intent is None:
                        return  # false trigger, already logged - see _interpret_audio
                else:
                    self._log("Hey Peer detected.")
                    instruction_text = self.get_instruction()
                    self._log(f"> {instruction_text}")
                    intent = self.nemotron.interpret_text(
                        instruction_text,
                        self._skill_context(),
                        watched_files=self._watched_files(),
                        watched_folders=self._watched_folders(),
                    )
            except Exception as exc:
                self._log(f"Failed to interpret the instruction: {exc}")
                return
            self._dispatch_intent(intent)
        finally:
            if self.debug_window is not None:
                self.debug_window.set_state("listening")
            if self._wake_listener is not None:
                self._wake_listener.unmute()

    def _interpret_audio(self, audio: np.ndarray) -> "Intent | None":
        """Transcribes the captured audio locally (Nemotron via this Nebius
        endpoint doesn't accept audio input - see heypeer/wakeword/stt.py and
        heypeer/nemotron/client.py's module docstrings for why) and sends the
        resulting text, plus a screenshot, to Nemotron for the reasoning.

        `audio` starts ~2s *before* the trigger (see the listener's
        prebuffer), so the wake word itself is in the transcript. That's used
        for two things before anything else happens: confirming this wasn't a
        false trigger (returns None if so - the small always-on detector fires
        on plenty of ordinary speech, see heypeer/wakeword/verify.py), and
        stripping the wake word out so it doesn't leak into the instruction
        Nemotron sees."""
        import tempfile

        import pyautogui

        from heypeer.wakeword.stt import transcribe
        from heypeer.wakeword.verify import contains_wake_word, strip_wake_word

        transcript = transcribe(audio)
        if not transcript:
            return None  # silence/noise - nothing was actually said

        if not contains_wake_word(transcript):
            # Logged quietly, not spoken: this is the common case for a false
            # trigger, and announcing every one of them out loud would be
            # worse than the false trigger itself.
            self._log(f'Ignored (no wake word in "{transcript}").')
            return None

        self._log("Hey Peer detected.")
        instruction_text = strip_wake_word(transcript)
        self._log(f"> {instruction_text}")
        if not instruction_text:
            return Intent(action="unknown", skill_id=None, n_repetitions=1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Downscaled JPEG, not a full-resolution PNG. The screenshot is
            # only context ("what is the user looking at"), and a 1920x1080
            # PNG is ~730 KB once base64-encoded — measured ~23x larger than
            # a 768px JPEG carrying the same context. That upload was a real
            # part of the "action takes too long" delay the user reported.
            screenshot_path = Path(tmp_dir) / "screenshot.jpg"
            shot = pyautogui.screenshot()
            shot.thumbnail((SCREENSHOT_MAX_PX, SCREENSHOT_MAX_PX))
            shot.convert("RGB").save(
                str(screenshot_path), format="JPEG", quality=SCREENSHOT_QUALITY
            )
            return self.nemotron.interpret_text(
                instruction_text,
                self._skill_context(),
                watched_files=self._watched_files(),
                watched_folders=self._watched_folders(),
                screenshot_path=str(screenshot_path),
            )

    def _handle_instruction(self, instruction_text: str) -> None:
        """Text-only path used by the tray's manual prompt and by tests.
        Mutes the wake-word listener for the same reason `on_wake_word` does
        (see `_on_wake_detected`) - the spoken narration this triggers
        shouldn't be picked up by a concurrently-running wake-word listener
        either."""
        if self._wake_listener is not None:
            self._wake_listener.mute()
        try:
            intent = self.nemotron.interpret_text(
                instruction_text,
                self._skill_context(),
                watched_files=self._watched_files(),
                watched_folders=self._watched_folders(),
            )
            self._dispatch_intent(intent)
        finally:
            if self._wake_listener is not None:
                self._wake_listener.unmute()

    def _dispatch_intent(self, intent: Intent) -> None:
        if _has_placeholder_name(intent):
            # Real bug this guards against: a truncated instruction ("Déplace
            # le fichier 4.", no destination) made Nemotron answer
            # dest_folder="unknown", and Hey Peer dutifully created a folder
            # literally named "unknown" and moved the file into it. A
            # placeholder is Nemotron saying it doesn't know - treat it that
            # way instead of taking it literally as a name.
            self._log("Hey Peer didn't get a clear enough target for that instruction.")
            self._speak("Je n'ai pas bien compris, peux-tu répéter ?")
            return
        if intent.action == "run_skill" and intent.skill_id is not None:
            self._run_skill_intent(intent)
        elif intent.action == "move_file" and intent.src_filename and intent.dest_folder:
            self._run_file_action(
                narration=f"Je déplace {intent.src_filename} vers {intent.dest_folder}.",
                run=lambda: move_single_file(self.watched_dir, intent.src_filename, intent.dest_folder),
                done=lambda path: f"Done: moved to {path}.",
            )
        elif intent.action == "rename_file" and intent.src_filename and intent.new_name:
            self._run_file_action(
                narration=f"Je renomme {intent.src_filename} en {intent.new_name}.",
                run=lambda: rename_file(self.watched_dir, intent.src_filename, intent.new_name),
                done=lambda path: f"Done: renamed to {path}.",
            )
        elif intent.action == "create_file" and intent.target_name:
            self._run_file_action(
                narration=f"Je crée le fichier {intent.target_name}.",
                run=lambda: create_file(self.watched_dir, intent.target_name),
                done=lambda path: f"Done: created {path}.",
            )
        elif intent.action == "create_folder" and intent.target_name:
            self._run_file_action(
                narration=f"Je crée le dossier {intent.target_name}.",
                run=lambda: create_folder(self.watched_dir, intent.target_name),
                done=lambda path: f"Done: created {path}.",
            )
        elif intent.action == "delete_file" and intent.src_filename:
            self._run_file_action(
                narration=f"Je supprime {intent.src_filename}.",
                run=lambda: delete_file(self.watched_dir, intent.src_filename),
                done=lambda path: f"Done: moved {path} to the recycle bin.",
            )
        else:
            self._log("Hey Peer didn't recognize a known skill or file action in that instruction.")
            self._speak("Je n'ai pas compris cette instruction.")

    def _run_skill_intent(self, intent: Intent) -> None:
        skill = self.memory.get(intent.skill_id)
        if skill is None:
            self._log(f"Nemotron referenced an unknown skill id: {intent.skill_id}")
            return

        times = f" {intent.n_repetitions} fois" if intent.n_repetitions > 1 else ""
        self._speak_async(f"Je fais : {skill.name}{times}.")

        runner = SkillRunner(
            verify_step=lambda png: self.nemotron.verify_screen(
                png, expected_context=f'next step of "{skill.name}"'
            )
        )
        self.tray.set_status(Status.EXECUTING)
        try:
            runner.run(skill, intent.n_repetitions)
            self._log(f'Done: "{skill.name}" x{intent.n_repetitions}.')
        except ExecutionAborted as exc:
            self._log(f"Stopped mid-replay: {exc}")
            self._speak("Je me suis arrêté en cours de route, quelque chose semblait anormal.")
        finally:
            self.tray.set_status(Status.LISTENING if self.tray.auto_mode else Status.OFF)

    def _run_file_action(
        self,
        narration: str,
        run: "Callable[[], Path]",
        done: "Callable[[Path], str]",
    ) -> None:
        """Shared body for every direct, one-off file action (move/rename/
        create file/create folder/delete) - Nemotron resolves which one and
        the file/name(s) involved, and it runs immediately (no confirmation
        step, see module docstring).

        The narration is spoken *without waiting for it to finish*, and the
        action runs straight away. Speaking synchronously first meant the
        file didn't move until a whole sentence had played, which is a large
        part of what the user experienced as "l'action prend trop de temps".

        Nothing is spoken afterwards either: saying what it's doing already
        tells the user it happened, so a trailing "C'est fait." was pure
        repetition. Only failures still get a spoken message, since those
        are the case where the narration would otherwise be a lie."""
        if self.watched_dir is None:
            self._log("No watched directory configured - can't resolve a direct file action.")
            return

        self._speak_async(narration)
        self.tray.set_status(Status.EXECUTING)
        try:
            result_path = run()
            self._log(done(result_path))
        except ExecutionAborted as exc:
            self._log(f"Stopped: {exc}")
            self._speak("Je n'ai pas pu faire ça, quelque chose semblait anormal.")
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
        capture_input=settings.capture_input,
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
