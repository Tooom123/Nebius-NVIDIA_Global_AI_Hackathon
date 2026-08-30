"""Entry point wiring Hey Peer together.

Flow: the wake word fires, its audio is verified, the indicator drops in,
the spoken instruction is recorded and transcribed locally, and Nemotron
turns it into one file action - move, rename, create, delete or undo -
which runs immediately. There is no confirmation step; undo and the
watched-directory containment check in `executor/runner.py` are what replace
it.

Hey Peer used to also watch mouse and keyboard activity, learn repeated
sequences as replayable "skills", and offer them to Nemotron. That is all
gone. In practice the learned skills never matched a spoken instruction,
they bloated every prompt, and the global input hooks feeding them cost real
performance on the user's machine.

The wake-word listener's callbacks fire from its own audio thread, which
must stay cheap and non-blocking to keep reading the mic smoothly. It only
enqueues onto `HeyPeer._detections` rather than handling the instruction
inline - blocking calls like `input()` were found not to actually wait for
keyboard input when called from that thread on Windows (confirmed
empirically: identical code worked fine on the main thread). Whichever
thread drains that queue is where instruction handling happens.

By default this runs as a background app with a system tray icon. Pass
`--cli` for the foreground console loop, which also shows a detached tray
icon so "Quitter" works as a stop button instead of Task Manager.
"""

import argparse
import atexit
import queue
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from heypeer.config import load_settings
from heypeer.executor import undo
from heypeer.executor.runner import (
    ExecutionAborted,
    create_file,
    create_folder,
    delete_file,
    move_single_file,
    rename_file,
    resolve_existing_filename,
)
from heypeer.nemotron.client import NemotronClient
from heypeer.nemotron.intent import Intent
from heypeer.tray.app import Status, TrayApp
from heypeer.tray.debug_window import DebugWindow

GetInstruction = Callable[[], str]

# How long the indicator takes to drop in. Recording waits this out so the
# blob is on screen before Hey Peer starts listening - otherwise the user is
# already mid-sentence by the time the cue appears, and the shape never seems
# to react to their voice.
INDICATOR_SLIDE_SECONDS = 0.45

_SHUTDOWN = object()  # sentinel put on HeyPeer._detections to unblock a consumer loop


def _default_get_instruction() -> str:
    return input("Hey Peer heard you. What do you want to do? ")


# Values Nemotron returns to mean "I couldn't determine this" — they must
# never be taken literally as a file/folder name (see `_has_placeholder_name`).
_PLACEHOLDER_NAMES = {"unknown", "none", "null", "n/a", "undefined", "inconnu", ""}


def _has_placeholder_name(intent: Intent) -> bool:
    """Whether any name field on `intent` is a stand-in for "not determined"
    rather than a real name the user asked for."""
    names = (intent.src_filename, intent.dest_folder, intent.new_name, intent.target_name)
    return any(name is not None and name.strip().lower() in _PLACEHOLDER_NAMES for name in names)


class HeyPeer:
    """Wires wake word -> transcription -> interpretation -> execution.

    Split out as a class (rather than one long function) so each stage can be
    exercised independently in tests via constructor injection.
    """

    def __init__(
        self,
        nemotron: NemotronClient,
        watched_dir: Path | None = None,
        get_instruction: GetInstruction = _default_get_instruction,
        wakeword_debug: bool = False,
        wakeword_threshold: float = 0.9,
        debug_window: DebugWindow | None = None,
    ) -> None:
        self.wakeword_debug = wakeword_debug
        self.wakeword_threshold = wakeword_threshold
        self.debug_window = debug_window
        self.nemotron = nemotron
        self.get_instruction = get_instruction
        self.watched_dir = watched_dir
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
        # Reversal records for completed file actions - the safety net that
        # replaced the confirmation gate. See heypeer/executor/undo.py.
        self._undo_stack = undo.UndoStack()
        # Bumped whenever a follow-up window opens, so a window that has
        # since been superseded can't hide the indicator out from under a
        # turn that started after it.
        self._followup_generation = 0

    def _log(self, message: str) -> None:
        """The conversation lives in the terminal now - the debug window is
        just the visual state/level indicator (see `debug_window.py`).

        Printing is made unfailing on purpose. Some of what passes through
        here is model-generated (a clarifying question, a filename it read
        back), so its characters are not ours to control: Nemotron returned a
        non-breaking hyphen once and the resulting UnicodeEncodeError from a
        cp1252 console took down the whole app mid-turn. A mangled character
        is a cosmetic problem; losing the session over one is not.
        """
        try:
            print(message)
        except UnicodeEncodeError:
            encoding = getattr(sys.stdout, "encoding", None) or "ascii"
            print(message.encode(encoding, errors="replace").decode(encoding))

    def _set_auto_mode(self, enabled: bool) -> None:
        """"Mode auto": is Hey Peer listening for the wake word and able to
        act on it."""
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
            ready_delay=INDICATOR_SLIDE_SECONDS,
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
            from heypeer.wakeword.stt import VERIFY_MODEL, transcribe
            from heypeer.wakeword.verify import contains_wake_word

            # No VAD filter: this clip is ~2s and the filter frequently
            # discards all of it, which read as "Hey Peer ignores me and I
            # have to repeat myself". See `transcribe`.
            transcript = transcribe(
                pre_trigger_audio, use_vad=False, model_name=VERIFY_MODEL
            )
            if not transcript:
                # Heard *something* (the detector fired) but couldn't make
                # out words. That's uncertainty, not a refusal — keep
                # recording and let the full-audio check in
                # `_interpret_audio`, which has the whole instruction to work
                # with, be the one that decides. No chime, since we can't
                # honestly confirm yet.
                return True
            if not contains_wake_word(transcript):
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
        return True

    def _arm_followup(self) -> None:
        """Lets the next command skip the wake word for a few seconds, so a
        conversation can continue naturally instead of restarting.

        Also keeps the indicator on screen for that window. It used to slide
        away the moment a turn ended - including right after Hey Peer had
        asked a question - which reads as the conversation being over when it
        is precisely still open and waiting for an answer."""
        if self._wake_listener is None:
            return
        # Imported here, not at module level. `listener` pulls onnxruntime and
        # openwakeword, and this module is re-imported in the overlay's child
        # process by multiprocessing's spawn - so a top-level import loaded
        # those native runtimes twice, in two processes, alongside PortAudio
        # and GDI. That segfaulted the app on Windows, and cost 0.6s of
        # startup besides.
        from heypeer.wakeword.listener import FOLLOWUP_WINDOW_SECONDS

        self._wake_listener.arm_followup()
        self._followup_generation += 1
        generation = self._followup_generation
        if self.debug_window is not None:
            self.debug_window.set_state("awaiting")

        def stand_down() -> None:
            # Only if no new turn started meanwhile, or this would clobber
            # the state of whatever is happening now.
            if self._followup_generation == generation and self.debug_window is not None:
                self.debug_window.set_state("listening")

        timer = threading.Timer(FOLLOWUP_WINDOW_SECONDS, stand_down)
        timer.daemon = True
        timer.start()

    def _on_wake_detected(self, audio: np.ndarray, followup: bool = False) -> None:
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
        self._detections.put((audio, followup))

    def _stop_voice(self) -> None:
        if self._wake_listener is not None:
            self._wake_listener.stop()
            self._wake_listener = None
        if self.debug_window is not None:
            self.debug_window.set_state("idle")

    def _on_quit(self) -> None:
        self._stop_voice()
        self._detections.put(_SHUTDOWN)  # unblocks a consumer loop waiting on detections

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

    def on_wake_word(self, audio: np.ndarray | None = None, followup: bool = False) -> None:
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
        opened_with = self._followup_generation
        try:
            try:
                if audio is not None and len(audio) > 0:
                    intent = self._interpret_audio(audio, followup=followup)
                    if intent is None:
                        return  # false trigger, already logged - see _interpret_audio
                else:
                    self._log("Hey Peer detected.")
                    instruction_text = self.get_instruction()
                    self._log(f"> {instruction_text}")
                    intent = self.nemotron.interpret_text(
                        instruction_text,
                        [],
                        watched_files=self._watched_files(),
                        watched_folders=self._watched_folders(),
                    )
            except Exception as exc:
                self._log(f"Failed to interpret the instruction: {exc}")
                return
            self._dispatch_intent(intent)
        finally:
            if self.debug_window is not None and self._followup_generation == opened_with:
                # Unchanged generation means nothing armed a follow-up during
                # this turn, so the exchange really is over.
                self.debug_window.set_state("listening")
            if self._wake_listener is not None:
                self._wake_listener.unmute()

    def _interpret_audio(self, audio: np.ndarray, followup: bool = False) -> "Intent | None":
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
        from heypeer.wakeword.stt import transcribe
        from heypeer.wakeword.verify import contains_wake_word, strip_wake_word

        transcript = transcribe(audio)
        if not transcript:
            return None  # silence/noise - nothing was actually said

        if followup:
            # A follow-up turn has no wake word in it by design — the user is
            # continuing, not re-summoning. Checking for one would reject
            # every single one of them.
            self._log("Follow-up.")
            instruction_text = transcript
        else:
            if not contains_wake_word(transcript):
                # Logged quietly, not spoken: this is the common case for a
                # false trigger, and announcing every one out loud would be
                # worse than the false trigger itself.
                self._log(f'Ignored (no wake word in "{transcript}").')
                return None
            self._log("Hey Peer detected.")
            instruction_text = strip_wake_word(transcript)
        self._log(f"> {instruction_text}")
        if not instruction_text:
            return Intent(action="unknown", skill_id=None, n_repetitions=1)

        # No screenshot: this deployment now rejects any non-string message
        # content with a 400 ("Input should be a valid string"), so sending
        # one broke every request. See `NemotronClient.interpret_text`'s
        # docstring. Nothing is lost for file actions — the grounding that
        # matters is the real file/folder listing, not a picture of the
        # screen — and skipping the capture and upload is faster too.
        return self.nemotron.interpret_text(
            instruction_text,
            [],
            watched_files=self._watched_files(),
            watched_folders=self._watched_folders(),
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
                [],
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
        if intent.action == "undo":
            self._run_undo()
        elif intent.action == "ask":
            # Nemotron recognised the intent but is missing a piece. Saying
            # exactly what's missing is far more useful than "je n'ai pas
            # compris", which leaves the user guessing what to rephrase.
            question = intent.question or "Peux-tu préciser ?"
            self._log(f"Needs clarification: {question}")
            self._speak(question)
            self._arm_followup()
        elif intent.action == "move_file" and intent.src_filename and intent.dest_folder:
            source = self._resolved_path(intent.src_filename)
            self._run_file_action(
                narration=f"Je déplace {intent.src_filename} vers {intent.dest_folder}.",
                run=lambda: move_single_file(self.watched_dir, intent.src_filename, intent.dest_folder),
                done=lambda path: f"Done: moved to {path}.",
                undo_factory=(lambda path: undo.moved(source, path)) if source else None,
            )
        elif intent.action == "rename_file" and intent.src_filename and intent.new_name:
            source = self._resolved_path(intent.src_filename)
            self._run_file_action(
                narration=f"Je renomme {intent.src_filename} en {intent.new_name}.",
                run=lambda: rename_file(self.watched_dir, intent.src_filename, intent.new_name),
                done=lambda path: f"Done: renamed to {path}.",
                undo_factory=(lambda path: undo.renamed(source, path)) if source else None,
            )
        elif intent.action == "create_file" and intent.target_name:
            self._run_file_action(
                narration=f"Je crée le fichier {intent.target_name}.",
                run=lambda: create_file(self.watched_dir, intent.target_name),
                done=lambda path: f"Done: created {path}.",
                undo_factory=undo.created_file,
            )
        elif intent.action == "create_folder" and intent.target_name:
            self._run_file_action(
                narration=f"Je crée le dossier {intent.target_name}.",
                run=lambda: create_folder(self.watched_dir, intent.target_name),
                done=lambda path: f"Done: created {path}.",
                undo_factory=undo.created_folder,
            )
        elif intent.action == "delete_file" and intent.src_filename:
            self._run_file_action(
                narration=f"Je supprime {intent.src_filename}.",
                run=lambda: delete_file(self.watched_dir, intent.src_filename),
                done=lambda path: f"Done: moved {path} to the recycle bin.",
                undo_factory=undo.deleted,
            )
        else:
            self._log("Hey Peer didn't recognize a known skill or file action in that instruction.")
            self._speak("Je n'ai pas compris cette instruction.")

    def _resolved_path(self, spoken_name: str) -> "Path | None":
        """Where a spoken filename actually points, resolved *before* the
        action runs — afterwards the file has moved or been renamed and the
        original path can no longer be recovered, which is what undo needs."""
        if self.watched_dir is None:
            return None
        resolved = resolve_existing_filename(self.watched_dir, spoken_name)
        return self.watched_dir / resolved if resolved else None

    def _run_undo(self) -> None:
        entry = self._undo_stack.pop()
        if entry is None:
            self._log("Nothing to undo.")
            self._speak("Il n'y a rien à annuler.")
            return
        if entry.undo is None:
            self._log(f"Not undoable: {entry.description} ({entry.not_undoable_reason})")
            self._speak(f"Je ne peux pas annuler ça : {entry.not_undoable_reason}.")
            return

        self._speak_async(f"J'annule {entry.description}.")
        try:
            entry.undo()
            self._log(f"Undone: {entry.description}.")
            self._arm_followup()
        except Exception as exc:
            self._log(f"Undo failed: {exc}")
            self._speak("Je n'ai pas réussi à annuler.")

    def _run_file_action(
        self,
        narration: str,
        run: "Callable[[], Path]",
        done: "Callable[[Path], str]",
        undo_factory: "Callable[[Path], undo.UndoEntry] | None" = None,
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
            if undo_factory is not None:
                # Recorded only on success, and only here: the resolved
                # filename and the final path are known at this point and
                # nowhere else.
                self._undo_stack.push(undo_factory(result_path))
            self._arm_followup()
        except ExecutionAborted as exc:
            self._log(f"Stopped: {exc}")
            self._speak("Je n'ai pas pu faire ça, quelque chose semblait anormal.")
        finally:
            self.tray.set_status(Status.LISTENING if self.tray.auto_mode else Status.OFF)


def _build_peer(with_debug_window: bool = False) -> HeyPeer:
    settings = load_settings()
    print("Hey Peer starting.")
    print(f"Nemotron model: {settings.nemotron_model_id}")
    print(f"Watching folder: {settings.watched_dir}")
    return HeyPeer(
        nemotron=NemotronClient(settings),
        watched_dir=settings.watched_dir,
        wakeword_debug=settings.wakeword_debug,
        wakeword_threshold=settings.wakeword_threshold,
        debug_window=DebugWindow() if with_debug_window else None,
    )


def run_tray() -> None:
    """Default entry point: a background app living in the system tray.

    "Mode auto" (wake-word listening) is a simple ON/OFF toggle in the tray
    menu and starts **ON**. `TrayApp.run()` blocks the calling thread with
    the tray's own event loop, so it must be called last, from the main
    thread.

    Note: on Windows, Ctrl+C in the console can't reliably interrupt the
    tray's native message loop - use the tray menu's "Quitter" to exit.
    """
    peer = _build_peer(with_debug_window=True)
    peer.tray.set_auto_mode(True)
    print("Icone dans la zone de notification. Mode auto (ecoute vocale) : ON.")
    print('Menu "Demander a Hey Peer..." disponible pour tester sans micro.')

    # Wake-word detections still need a consumer thread even in tray mode -
    # see module docstring on why on_wake_word can't run on the audio thread.
    def _drain_detections() -> None:
        while True:
            item = peer._detections.get()
            if item is _SHUTDOWN:
                return
            audio, followup = item
            peer.on_wake_word(audio, followup=followup)

    threading.Thread(target=_drain_detections, daemon=True).start()
    peer.tray.run()


def run_cli() -> None:
    """Foreground console loop - no separate tray host process needed, but a
    real (detached) tray icon still runs alongside it so "Quitter" works as a
    stop button instead of Task Manager. Enter simulates the wake word if no
    trained wake-word model is available."""
    peer = _build_peer(with_debug_window=True)
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
                audio, followup = item
                peer.on_wake_word(audio, followup=followup)
    finally:
        peer._on_quit()


def _configure_console() -> None:
    """Puts stdout/stderr into UTF-8 with replacement, where possible.

    Windows consoles default to a legacy code page (cp1252 here), which
    cannot represent much of what a language model emits. `errors="replace"`
    is the part that matters: it makes an unrepresentable character print as
    a placeholder instead of raising, which is the difference between a
    cosmetic blemish and the app dying mid-turn.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # not a real console, or an older stream object - harmless


def main() -> None:
    _configure_console()
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
