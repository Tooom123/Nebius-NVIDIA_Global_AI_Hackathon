"""Entry point wiring Hey Peer together.

Flow, in the order the user experiences it: the wake word fires, its audio is
verified, the indicator drops in, a chime confirms it is listening, the spoken
turn is recorded and transcribed locally, and Nemotron interprets it. Each
step waits for the one before - in particular the chime waits for the blob to
actually be on screen (`_on_ready_to_listen`), because the two together are
the "speak now" signal and a beep that arrives first is worse than no beep.

## A conversation, not a command line

Nemotron decides what kind of turn it was. Most are one file action - move,
rename, create, delete or undo - which runs immediately: there is no
confirmation step, and undo plus the watched-directory containment check in
`executor/runner.py` are what replace it. But a turn can equally be ordinary
conversation ("comment ca va ?"), or a question back when something is
missing ("vers quel dossier ?").

What ties those together is that an exchange has a *length*. Every answer
says whether it is finished; while it is not, the microphone stays open with
no wake word needed and what has been said so far is replayed to Nemotron on
the next turn. So "deplace facture" / "vers quel dossier ?" / "Archives"
works, and so does small talk that runs a few turns. The exchange ends when
the model says it has, when the task is done, or when the window closes with
nobody saying anything - and its history is dropped with it, so the next
"Hey Peer" starts clean.

The action list is deliberately open-ended: it will grow well past file
operations. The prompt's standing instruction is that anything it cannot do
is *answered*, never bent into the nearest action it does have - guessing at
an action nobody asked for is the one failure here that touches real files.

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
from heypeer.nemotron.intent import SPOKEN_ACTIONS, Intent
from heypeer.tray.app import Status, TrayApp
from heypeer.tray.debug_window import DebugWindow

GetInstruction = Callable[[], str]

# Longest Hey Peer will wait for the indicator to finish dropping in before
# chiming anyway. The wait itself is not timed - the overlay process says
# when the blob has actually landed (see `DebugWindow.wait_until_visible`) -
# so this is only the cap that stops a stalled or unsupported overlay from
# holding up a turn. Comfortably above the slide's own 0.28s.
INDICATOR_LANDING_TIMEOUT = 0.8

# How many exchange turns (user + assistant pairs) are replayed to Nemotron.
# Far beyond any real spoken conversation, which is over in a handful, while
# still bounding the prompt if one runs long.
HISTORY_TURNS = 8

# How long the microphone stays open, with no wake word, after Hey Peer has
# said something that expects an answer. Longer than the window after a
# completed action (`listener.FOLLOWUP_WINDOW_SECONDS`): being asked a
# question and having to think for a moment is normal, and having the
# assistant stop listening while you do is the thing that makes an assistant
# feel like a command line rather than a conversation.
CONVERSATION_WINDOW_SECONDS = 12.0

_SHUTDOWN = object()  # sentinel put on HeyPeer._detections to unblock a consumer loop


def _default_get_instruction() -> str:
    return input("Hey Peer heard you. What do you want to do? ")


# Values Nemotron returns to mean "I couldn't determine this" — they must
# never be taken literally as a file/folder name (see `_has_placeholder_name`).
_PLACEHOLDER_NAMES = {"unknown", "none", "null", "n/a", "undefined", "inconnu", ""}


def _bilingual(language: str, french: str, english: str) -> str:
    """`french` or `english`, matching what Nemotron reported it wrote its
    own narration in for this turn (`intent.language`).

    Only for Hey Peer's own *fixed* fallback strings — an unknown app, a
    failed launch, "nothing to undo". Nemotron's own `speech`/`question`
    text is never touched here; it already comes back in the right
    language (see `client.py`'s system prompt) and is spoken with
    `intent.language` picking the voice, not translated after the fact."""
    return english if language == "en" else french


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
        # What has been said so far in the exchange currently underway, as
        # chat messages. Sent with every interpretation so a turn can refer
        # to the last one ("et dans Archives du coup ?"), and cleared the
        # moment the exchange closes - see `_close_exchange`. Bounded, so a
        # long conversation cannot grow the prompt without limit.
        self._history: list[dict] = []
        # Whether the "add your Spotify credentials" hint has been printed
        # this run. It applies to every music request, and repeating it would
        # bury the line saying what actually happened.
        self._spotify_hint_shown = False

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
        """Warms both Whisper models in the background, and says so when it is
        done.

        The announcement is not cosmetic. Until this finishes, a "Hey Peer"
        skips verification (see `_verify_wake_word`) and the instruction after
        it waits on a cold model - so the first activation after launch really
        is less reliable than the ones after it, and the user should be able
        to see when that window has closed rather than infer it from Hey Peer
        behaving oddly."""
        try:
            from heypeer.wakeword.stt import preload

            preload()
            self._log("Hey Peer est pret (modeles de reconnaissance charges).")
        except Exception as exc:
            print(f"[stt] Whisper preload failed (will retry on first use): {exc}")

    def _preload_tts(self) -> None:
        try:
            from heypeer.tray.tts import preload

            preload()
        except Exception as exc:
            print(f"[tts] Piper voice preload failed (will retry on first use): {exc}")

    def _speak(self, text: str, language: "str | None" = "fr") -> None:
        """Speaks `text` aloud (Piper TTS) — best-effort: a TTS failure
        (missing audio output device, voice download failure, ...) must
        never block the actual execution flow. Muting the wake-word listener
        happens for the whole turn now (see `_on_wake_detected`/
        `on_wake_word`), not just here, so this no longer needs to touch it
        itself — kept as a no-op-safe method regardless.

        `language` picks the voice - "en" for an English one, anything else
        (including the default) the existing French one. Nemotron reports
        which language it just wrote in on every answer (see `nemotron/
        intent.py`); callers pass that straight through so what gets *said*
        matches what got *written* - answering in English text but reading
        it with the French voice would still sound wrong, just differently."""
        if self.debug_window is not None:
            self.debug_window.set_state("speaking")
        try:
            from heypeer.tray.tts import speak

            speak(text, language=language)
        except Exception as exc:
            print(f"[tts] Speak failed: {exc}")
        finally:
            if self.debug_window is not None:
                self.debug_window.set_state("listening")

    def _speak_async(self, text: str, language: "str | None" = "fr") -> None:
        """Speaks without blocking the caller. Used for narration that
        precedes an action: the action shouldn't wait for a whole sentence
        of speech to play before it happens."""
        threading.Thread(target=self._speak, args=(text, language), daemon=True).start()

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
            on_ready=self._on_ready_to_listen,
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

            from heypeer.wakeword.stt import is_loaded

            if not is_loaded(VERIFY_MODEL):
                # The model is still being warmed up in the background (see
                # `_preload_stt`). Loading it here would block *this* thread -
                # which is the one reading the microphone - for several
                # seconds, during which Hey Peer hears nothing at all. That is
                # what made the first "Hey Peer" after startup so often seem
                # to be ignored: it was not missed, it was answered long after
                # the user had given up and repeated themselves.
                #
                # So skip verification rather than wait for it. The detector's
                # own judgement stands for this one activation, and the full
                # transcript check in `_interpret_audio` still rejects the
                # turn if the wake word was not really there.
                self._log("[wakeword] Verification model still warming up - trusting the detector.")
                if self.debug_window is not None:
                    self.debug_window.set_state("recording")
                return True

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

        # Only the indicator here. The chime follows once it has actually
        # landed, in `_on_ready_to_listen` - a single unambiguous cue rather
        # than a sound and then, a moment later, something appearing on
        # screen.
        if self.debug_window is not None:
            self.debug_window.set_state("recording")
        return True

    def _on_ready_to_listen(self) -> None:
        """Waits for the blob to be on screen, sounds the cue, then lets
        recording start. This is the whole order the user asked for, in one
        place: "Hey Peer" -> the blob comes down -> the beep says it is
        listening -> the instruction.

        The wait is on the overlay process actually reporting the blob down,
        not on a sleep of the slide's nominal length. The slide only *starts*
        once that process has woken from its queue and drawn a frame, so a
        fixed sleep was systematically too short and the beep kept arriving
        while the blob was still on its way.

        The chime is then played synchronously: the beep *is* the "speak now"
        signal, so the mic must open after it rather than during it -
        otherwise the recording opens with the beep, which also reads as
        speech to the energy-based end-pointing. The asset is trimmed to
        ~0.3s so the wait is barely perceptible."""
        from heypeer.wakeword.listener import play_activation_chime

        if self.debug_window is not None:
            if not self.debug_window.wait_until_visible(INDICATOR_LANDING_TIMEOUT):
                # A stalled overlay must not cost the user their turn: chime
                # anyway and start listening.
                self._log("[ui] Indicator did not report landing in time - chiming anyway.")
        try:
            play_activation_chime(blocking=True)
        except Exception as exc:  # best-effort - never hold a turn up for a beep
            print(f"[wakeword] Chime playback failed: {exc}")

    def _remember(self, user_text: str, assistant_text: str) -> None:
        """Records one exchange turn for the next interpretation to see."""
        if user_text:
            self._history.append({"role": "user", "content": user_text})
        if assistant_text:
            self._history.append({"role": "assistant", "content": assistant_text})
        # Keeping only the recent turns bounds the prompt. Well beyond any
        # real spoken exchange, which is over in a handful of turns.
        del self._history[:-HISTORY_TURNS * 2]

    def _close_exchange(self) -> None:
        """Ends the conversation: forget what was said and stop listening for
        a reply that needs no wake word.

        Called when the model says the exchange is over, and whenever a turn
        ends without anything having opened a follow-up window. Forgetting
        matters as much as the microphone does: carrying an old exchange into
        the next "Hey Peer" would have the assistant answering a question
        nobody just asked."""
        self._history.clear()
        if self._wake_listener is not None:
            self._wake_listener.cancel_followup()

    def _arm_followup(self, seconds: "float | None" = None) -> None:
        """Lets the next turn skip the wake word for a few seconds, so a
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

        if seconds is None:
            seconds = FOLLOWUP_WINDOW_SECONDS
        self._wake_listener.arm_followup(seconds)
        self._followup_generation += 1
        generation = self._followup_generation
        if self.debug_window is not None:
            self.debug_window.set_state("awaiting")

        def stand_down() -> None:
            # The window closed with nothing said, so the conversation is
            # over whatever the model hoped - drop the history with it.
            if self._followup_generation != generation:
                return  # a new turn started meanwhile; leave it alone
            self._history.clear()
            if self.debug_window is not None:
                self.debug_window.set_state("listening")

        timer = threading.Timer(seconds, stand_down)
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
                    interpreted = self._interpret_audio(audio, followup=followup)
                    if interpreted is None:
                        return  # false trigger, already logged - see _interpret_audio
                    intent, instruction_text = interpreted
                else:
                    self._log("Hey Peer detected.")
                    instruction_text = self.get_instruction()
                    self._log(f"> {instruction_text}")
                    intent = self._interpret(instruction_text)
            except Exception as exc:
                self._log(f"Failed to interpret the instruction: {exc}")
                return
            self._dispatch_intent(intent, instruction_text)
        finally:
            if self._followup_generation == opened_with:
                # Unchanged generation means nothing armed a follow-up during
                # this turn, so the exchange really is over: stop listening
                # for a reply, and forget what was said.
                self._close_exchange()
                if self.debug_window is not None:
                    self.debug_window.set_state("listening")
            if self._wake_listener is not None:
                self._wake_listener.unmute()

    def _interpret(self, instruction_text: str, followup: bool = False) -> Intent:
        """Resolves one instruction to an `Intent` - the local fast path
        first, Nemotron otherwise.

        Only tried on a fresh turn: a follow-up (`followup=True`, or an
        open exchange - non-empty history) always goes straight to Nemotron.
        A follow-up continues a conversation Nemotron itself is holding the
        context for - "et le deuxieme aussi" cannot be understood from a
        fixed sentence shape, and that is exactly the case an LLM's grasp of
        context is for.

        Both checks matter: in real use, `self._history` alone would be
        enough - a follow-up window only ever opens after `_remember` has
        already recorded the turn that opened it (see `_dispatch_intent`),
        so history is never empty during one. But this project's own tests
        construct a follow-up turn directly, without a preceding real turn
        to populate history first - a reasonable, deliberate shortcut this
        method has to honour too, not silently defeat.
        """
        if not followup and not self._history and self.watched_dir is not None:
            from heypeer.nemotron.fast_path import try_fast_path

            fast = try_fast_path(instruction_text, self.watched_dir, self._watched_folders())
            if fast is not None:
                self._log("Handled locally, without asking the model.")
                return fast

        from heypeer import memory as memory_store

        return self.nemotron.interpret_text(
            instruction_text,
            [],
            watched_files=self._watched_files(),
            watched_folders=self._watched_folders(),
            history=list(self._history),
            memory=memory_store.as_context(),
        )

    def _interpret_audio(
        self, audio: np.ndarray, followup: bool = False
    ) -> "tuple[Intent, str] | None":
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
        Nemotron sees.

        Returns the intent together with the words it was derived from, which
        the caller records into the exchange history."""
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
            return Intent(action="unknown", skill_id=None, n_repetitions=1), ""

        # No screenshot: this deployment now rejects any non-string message
        # content with a 400 ("Input should be a valid string"), so sending
        # one broke every request. See `NemotronClient.interpret_text`'s
        # docstring. Nothing is lost for file actions — the grounding that
        # matters is the real file/folder listing, not a picture of the
        # screen — and skipping the capture and upload is faster too.
        return (self._interpret(instruction_text, followup=followup), instruction_text)

    def _handle_instruction(self, instruction_text: str) -> None:
        """Text-only path used by the tray's manual prompt and by tests.
        Mutes the wake-word listener for the same reason `on_wake_word` does
        (see `_on_wake_detected`) - the spoken narration this triggers
        shouldn't be picked up by a concurrently-running wake-word listener
        either."""
        if self._wake_listener is not None:
            self._wake_listener.mute()
        try:
            intent = self._interpret(instruction_text)
            self._dispatch_intent(intent, instruction_text)
        finally:
            if self._wake_listener is not None:
                self._wake_listener.unmute()

    def _dispatch_intent(self, intent: Intent, instruction_text: str = "") -> None:
        """Carries out one interpreted turn, and decides whether the exchange
        stays open afterwards.

        `instruction_text` is what the user said, recorded into the history
        alongside whatever Hey Peer says back so the *next* turn can refer to
        this one."""
        language = intent.language or "fr"
        if intent.action in SPOKEN_ACTIONS:
            # Nothing to do to the computer: this turn is an answer. Covers
            # both ordinary conversation ("comment ca va ?") and a missing
            # piece Nemotron needs before it can act ("vers quel dossier ?").
            message = intent.speech or intent.question
            if not message:
                # It chose to speak and then said nothing. Better to admit
                # that than to stand silent.
                message = _bilingual(language, "Je n'ai pas bien compris, peux-tu reformuler ?",
                                     "I didn't quite understand, could you rephrase?")
            self._log(f"Hey Peer: {message}")
            # Spoken synchronously, and only then is the follow-up window
            # opened: opening it first would have the microphone listening
            # while Hey Peer is still talking, and it would answer itself.
            self._speak(message, language=language)
            self._remember(instruction_text, message)
            # "ask" is a request for an answer by construction, so it holds
            # the exchange open whatever `end_turn` says. Leaving that to the
            # model would mean one careless `true` ends the conversation
            # immediately after Hey Peer has asked the user a question - the
            # exact behaviour that made the blob slide away mid-exchange
            # before there was a follow-up window at all.
            if intent.end_turn and intent.action != "ask":
                self._close_exchange()
            else:
                self._arm_followup(CONVERSATION_WINDOW_SECONDS)
            return
        if _has_placeholder_name(intent):
            # Real bug this guards against: a truncated instruction ("Déplace
            # le fichier 4.", no destination) made Nemotron answer
            # dest_folder="unknown", and Hey Peer dutifully created a folder
            # literally named "unknown" and moved the file into it. A
            # placeholder is Nemotron saying it doesn't know - treat it that
            # way instead of taking it literally as a name.
            self._log("Hey Peer didn't get a clear enough target for that instruction.")
            self._speak(_bilingual(language, "Je n'ai pas bien compris, peux-tu répéter ?",
                                   "I didn't quite understand, could you repeat that?"), language=language)
            # A rephrasing is expected, so this is not the end of anything.
            self._arm_followup(CONVERSATION_WINDOW_SECONDS)
            return
        self._remember(instruction_text, intent.speech or "")
        if intent.action == "undo":
            self._run_undo(language)
        elif intent.action == "open_app" and intent.target_name:
            self._run_open_app(intent.target_name, intent.speech, language)
        elif intent.action == "play_music" and intent.query:
            self._run_play_music(intent.query, language)
        elif intent.action == "search_web" and intent.query:
            self._run_search_web(intent.query, intent.speech, language)
        elif intent.action == "adjust_volume" and intent.target_name:
            self._run_adjust_volume(intent.target_name, intent.speech, language)
        elif intent.action == "adjust_brightness" and intent.target_name:
            self._run_adjust_brightness(intent.target_name, intent.speech, language)
        elif intent.action == "maximize_window" and intent.target_name:
            self._run_window_control("maximize", intent.target_name, intent.speech, language)
        elif intent.action == "minimize_window" and intent.target_name:
            self._run_window_control("minimize", intent.target_name, intent.speech, language)
        elif intent.action == "close_window" and intent.target_name:
            self._run_window_control("close", intent.target_name, intent.speech, language)
        elif intent.action == "minimize_all":
            self._run_minimize_all(intent.speech, language)
        elif intent.action == "clipboard_copy":
            self._run_clipboard_copy(intent.speech, language)
        elif intent.action == "clipboard_read":
            self._run_clipboard_read(intent.speech, language)
        elif intent.action == "summarize_document" and intent.target_name:
            self._run_summarize_document(intent.target_name, intent.speech, language)
        elif intent.action == "read_screen":
            self._run_read_screen(instruction_text, intent.speech, language)
        elif intent.action == "analyze_code" and intent.target_name:
            self._run_analyze_code(intent.target_name, instruction_text, intent.speech, language)
        elif intent.action == "fix_code" and intent.target_name:
            self._run_fix_code(intent.target_name, instruction_text, intent.speech, language)
        elif intent.action == "debug_screen_code":
            self._run_debug_screen_code(instruction_text, intent.speech, language)
        elif intent.action == "remember_fact" and intent.content:
            self._run_remember_fact(intent.content, intent.speech, language)
        elif intent.action == "general_task" and intent.content:
            self._run_general_task(intent.content, intent.speech, language)
        elif intent.action == "move_file" and intent.src_filename and intent.dest_folder:
            source = self._resolved_path(intent.src_filename)
            self._run_file_action(
                narration=intent.speech or _bilingual(
                    language, f"Je déplace {intent.src_filename} vers {intent.dest_folder}.",
                    f"Moving {intent.src_filename} to {intent.dest_folder}."),
                run=lambda: move_single_file(self.watched_dir, intent.src_filename, intent.dest_folder),
                done=lambda path: f"Done: moved to {path}.",
                undo_factory=(lambda path: undo.moved(source, path)) if source else None,
                language=language,
            )
        elif intent.action == "rename_file" and intent.src_filename and intent.new_name:
            source = self._resolved_path(intent.src_filename)
            self._run_file_action(
                narration=intent.speech or _bilingual(
                    language, f"Je renomme {intent.src_filename} en {intent.new_name}.",
                    f"Renaming {intent.src_filename} to {intent.new_name}."),
                run=lambda: rename_file(self.watched_dir, intent.src_filename, intent.new_name),
                done=lambda path: f"Done: renamed to {path}.",
                undo_factory=(lambda path: undo.renamed(source, path)) if source else None,
                language=language,
            )
        elif intent.action == "create_file" and intent.target_name:
            self._run_file_action(
                narration=intent.speech or _bilingual(
                    language, f"Je crée le fichier {intent.target_name}.",
                    f"Creating the file {intent.target_name}."),
                run=lambda: create_file(self.watched_dir, intent.target_name),
                done=lambda path: f"Done: created {path}.",
                undo_factory=undo.created_file,
                language=language,
            )
        elif intent.action == "create_folder" and intent.target_name:
            self._run_file_action(
                narration=intent.speech or _bilingual(
                    language, f"Je crée le dossier {intent.target_name}.",
                    f"Creating the folder {intent.target_name}."),
                run=lambda: create_folder(self.watched_dir, intent.target_name),
                done=lambda path: f"Done: created {path}.",
                undo_factory=undo.created_folder,
                language=language,
            )
        elif intent.action == "delete_file" and intent.src_filename:
            self._run_file_action(
                narration=intent.speech or _bilingual(
                    language, f"Je supprime {intent.src_filename}.",
                    f"Deleting {intent.src_filename}."),
                run=lambda: delete_file(self.watched_dir, intent.src_filename),
                done=lambda path: f"Done: moved {path} to the recycle bin.",
                undo_factory=undo.deleted,
                language=language,
            )
        else:
            self._log("Hey Peer didn't recognize a known skill or file action in that instruction.")
            self._speak(_bilingual(language, "Je n'ai pas compris cette instruction.",
                                   "I didn't understand that instruction."), language=language)

    def _run_open_app(self, spoken_name: str, narration: "str | None", language: str = "fr") -> None:
        """Starts an application the user named.

        Refuses names it does not recognise rather than handing them to the
        OS - see `executor/apps.py`. "Lance Machin" costs one turn to say no
        to; the alternative is a language model choosing what to execute.

        Spotify is special-cased because "lance Spotify" means start it *and*
        start the music: opening the app alone leaves the user in silence
        looking at a player that has not begun.
        """
        from heypeer.executor.apps import LaunchFailed, launch, resolve_app

        app = resolve_app(spoken_name)
        if app is None:
            self._log(f"Unknown application: {spoken_name!r}")
            self._speak(_bilingual(language, f"Je ne connais pas l'application {spoken_name}.",
                                   f"I don't know the application {spoken_name}."), language=language)
            self._arm_followup(CONVERSATION_WINDOW_SECONDS)
            return

        self._speak_async(
            narration or _bilingual(language, f"J'ouvre {app.name}.", f"Opening {app.name}."),
            language=language,
        )
        try:
            if app.name == "Spotify":
                from heypeer.executor.spotify import launch_and_play

                launch_and_play()
            else:
                launch(app)
            self._log(f"Launched {app.name}.")
        except LaunchFailed as exc:
            self._log(f"Launch failed: {exc}")
            self._speak(_bilingual(language, f"Je n'ai pas réussi à ouvrir {app.name}.",
                                   f"I couldn't open {app.name}."), language=language)
        # No follow-up window: opening an app finishes the request. `on_wake_word`
        # closes the exchange and hides the blob for any turn that armed nothing,
        # so "end the turn" is spelled by not arming one.

    def _run_play_music(self, query: str, language: str = "fr") -> None:
        """Plays what the user asked for on Spotify.

        Three outcomes, deliberately said differently, because they send the
        user to three different places:

        * **Found it.** Play the track and name it - "Je lance Starman par
          David Bowie". The name comes from the resolved track, never from
          the model's sentence: it is the only version that describes what is
          actually about to play, and it is how the user notices the search
          matched something other than what they said.
        * **Nothing matched.** Say so, and open the search so they can look.
        * **Not configured.** Also opens the search, but that is a setup step
          they have not done, not a failed search. Reporting it as "je n'ai
          pas trouve" sends them off trying to pronounce the title better.

        None of them opens a follow-up window. Starting music is the end of
        the request, and holding the microphone open afterwards means holding
        it open *over the music* - which, through a headset, is exactly how
        Hey Peer ended up awake and listening to itself.
        """
        from heypeer.executor.spotify import (
            credentials_missing,
            find_track,
            play_track,
            play_uri,
            search_uri,
        )

        settings = load_settings()
        if credentials_missing(settings.spotify_client_id, settings.spotify_client_secret):
            self._log(f"Spotify search is not configured - opening the search for {query!r}.")
            self._print_spotify_setup_hint()
            self._speak_async(_bilingual(
                language,
                "Je ne peux pas encore lancer un titre précis, il me manque la "
                f"configuration Spotify. J'ouvre la recherche pour {query}.",
                "I can't play a specific track yet, Spotify isn't configured. "
                f"Opening the search for {query} instead.",
            ), language=language)
            play_uri(search_uri(query))
            return

        track = find_track(query, settings.spotify_client_id, settings.spotify_client_secret)
        if track is None:
            self._log(f"Nothing on Spotify matched {query!r} - opening the search instead.")
            self._speak_async(_bilingual(
                language, f"Je n'ai pas trouvé {query} sur Spotify, j'ouvre la recherche.",
                f"I couldn't find {query} on Spotify, opening the search instead.",
            ), language=language)
            play_uri(search_uri(query))
            return

        spoken = track.spoken(language)
        self._speak_async(_bilingual(language, f"Je lance {spoken}.", f"Playing {spoken}."), language=language)
        play_track(track.uri)
        self._log(f"Playing {spoken} ({track.uri}).")

    def _print_spotify_setup_hint(self) -> None:
        """Says once per run how to make "lance Starman de David Bowie"
        actually play it. Once, because this fires on every music request and
        the console is where the user reads what happened."""
        if self._spotify_hint_shown:
            return
        self._spotify_hint_shown = True
        self._log(
            "\n  Pour lancer directement un titre, ajoute dans .env :\n"
            "    SPOTIFY_CLIENT_ID=...\n"
            "    SPOTIFY_CLIENT_SECRET=...\n"
            "  (application gratuite a creer sur developer.spotify.com - ces\n"
            "   identifiants autorisent la recherche et rien d'autre : pas de\n"
            "   connexion, pas de Premium, aucun acces a ton compte.)\n"
        )

    def _run_search_web(self, query: str, narration: "str | None", language: str = "fr") -> None:
        """Opens a web search for `query`.

        The query is percent-encoded into a fixed search URL rather than the
        model being asked for an address - see `apps.search_url`. A search
        string can say anything; a URL can *go* anywhere.
        """
        from heypeer.executor.apps import open_url, search_url

        self._speak_async(
            narration or _bilingual(language, f"Je cherche {query}.", f"Searching for {query}."),
            language=language,
        )
        try:
            open_url(search_url(query))
            self._log(f"Searching the web for {query!r}.")
        except Exception as exc:
            self._log(f"Web search failed: {exc}")
            self._speak(_bilingual(language, "Je n'ai pas réussi à ouvrir le navigateur.",
                                   "I couldn't open the browser."), language=language)

    def _run_adjust_volume(self, target: str, narration: "str | None", language: str = "fr") -> None:
        """`target` is "up", "down", or "mute" (a toggle, not a direction -
        see `system.volume_mute_toggle`). Always "succeeds" from here: the
        multimedia keys this sends exist on every Windows machine, there is
        nothing to fail open the way launching an app or a browser can."""
        from heypeer.executor import system

        self._speak_async(narration or _bilingual(
            language,
            {"up": "Je monte le son.", "down": "Je baisse le son.", "mute": "Je coupe le son."}[target],
            {"up": "Turning the volume up.", "down": "Turning the volume down.",
             "mute": "Muting."}[target],
        ), language=language)
        if target == "mute":
            system.volume_mute_toggle()
        elif target == "up":
            system.volume_up()
        else:
            system.volume_down()

    def _run_adjust_brightness(self, target: str, narration: "str | None", language: str = "fr") -> None:
        """Unlike volume, this can genuinely fail on correctly-working
        hardware - most external desktop monitors have no software
        brightness control at all (see `system.py`'s module docstring) -
        so the narration is spoken only once the attempt is known to have
        worked, not optimistically beforehand like the other handlers here."""
        from heypeer.executor import system

        ok = system.adjust_brightness(target)
        if ok:
            self._speak_async(narration or _bilingual(
                language,
                "Je monte la luminosité." if target == "up" else "Je baisse la luminosité.",
                "Turning the brightness up." if target == "up" else "Turning the brightness down.",
            ), language=language)
        else:
            self._log(f"Brightness adjustment ({target}) not supported on this display.")
            self._speak(_bilingual(
                language,
                "Je ne peux pas régler la luminosité sur cet écran.",
                "I can't adjust the brightness on this display.",
            ), language=language)

    def _run_window_control(
        self, operation: str, app_name: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """`operation` is "maximize", "minimize", or "close". A window not
        being found covers two different things from here - an app Hey Peer
        does not know (see `apps.resolve_app`), and a known app with no
        window currently open - and both get the same honest decline: either
        way, there is nothing to act on right now."""
        from heypeer.executor import system

        action = {"maximize": system.maximize_window, "minimize": system.minimize_window,
                  "close": system.close_window}[operation]
        ok = action(app_name)
        if ok:
            default = {
                "maximize": _bilingual(language, f"Je mets {app_name} en plein écran.",
                                       f"Maximizing {app_name}."),
                "minimize": _bilingual(language, f"Je minimise {app_name}.", f"Minimizing {app_name}."),
                "close": _bilingual(language, f"Je ferme {app_name}.", f"Closing {app_name}."),
            }[operation]
            self._speak_async(narration or default, language=language)
        else:
            self._log(f"No window found matching {app_name!r} to {operation}.")
            self._speak(_bilingual(
                language, f"Je ne vois pas de fenêtre ouverte pour {app_name}.",
                f"I can't find a window for {app_name}.",
            ), language=language)

    def _run_minimize_all(self, narration: "str | None", language: str = "fr") -> None:
        from heypeer.executor import system

        self._speak_async(narration or _bilingual(
            language, "Je minimise tout.", "Minimizing everything."), language=language)
        system.minimize_all()

    def _run_clipboard_copy(self, narration: "str | None", language: str = "fr") -> None:
        """There is no way to know from here whether anything was actually
        selected when Ctrl+C was sent - see `clipboard.copy_selection` -
        so the narration must never claim to know what got copied."""
        from heypeer.executor import clipboard

        self._speak_async(narration or _bilingual(language, "Copié.", "Copied."), language=language)
        clipboard.copy_selection()

    def _run_clipboard_read(self, narration: "str | None", language: str = "fr") -> None:
        """Two spoken parts, not one: an immediate intro (spoken while
        nothing has been read yet - Nemotron wrote it before the clipboard
        was available to it, see `clipboard_read`'s prompt block), then the
        actual content, summarized for speech *after* it's actually read.
        The intro is spoken synchronously so it lands before the summary,
        which needs a network round trip and would otherwise arrive first
        if both were fired async."""
        from heypeer.executor import clipboard

        content = clipboard.read()
        if not content:
            self._speak(_bilingual(
                language, "Le presse-papier est vide.", "The clipboard is empty.",
            ), language=language)
            return

        self._speak(narration or _bilingual(
            language, "Voici ce qu'il y a dans le presse-papier :",
            "Here's what's in the clipboard:",
        ), language=language)
        try:
            summary = self.nemotron.summarize_for_speech(content, language)
        except Exception as exc:
            self._log(f"Clipboard summarization failed: {exc}")
            summary = ""
        if summary:
            self._speak(summary, language=language)
        else:
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à lire le presse-papier.",
                "I couldn't read the clipboard.",
            ), language=language)

    def _run_summarize_document(
        self, filename: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """Same two-part shape as `_run_clipboard_read`: an intro spoken
        before anything has been read, then the summary once the document's
        text is actually extracted - reusing the exact same second-stage
        call (`summarize_for_speech`), since a document's text and clipboard
        text are both just "some text worth condensing" to it."""
        from heypeer.executor.documents import extract_text

        resolved = self.watched_dir and resolve_existing_filename(self.watched_dir, filename)
        if not resolved:
            self._speak(_bilingual(
                language, f"Je ne vois pas de fichier {filename}.",
                f"I can't find the file {filename}.",
            ), language=language)
            return

        text = extract_text(self.watched_dir / resolved)
        if not text:
            # Covers both "genuinely empty" and "a scanned PDF with no text
            # layer at all" - see documents.py's module docstring for why
            # there is no way to tell those apart without OCR, and both are
            # truthfully "nothing to summarize" either way.
            self._speak(_bilingual(
                language, f"Je n'ai rien pu extraire de {resolved}.",
                f"I couldn't extract anything from {resolved}.",
            ), language=language)
            return

        self._speak(narration or _bilingual(
            language, f"Voici un résumé de {resolved} :", f"Here's a summary of {resolved}:",
        ), language=language)
        try:
            summary = self.nemotron.summarize_for_speech(text, language)
        except Exception as exc:
            self._log(f"Document summarization failed: {exc}")
            summary = ""
        if summary:
            self._speak(summary, language=language)
        else:
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à résumer ce document.",
                "I couldn't summarize that document.",
            ), language=language)

    def _run_read_screen(
        self, question: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """`question` is the user's own instruction text, passed straight
        through to `describe_image` - "qu'est-ce qu'il y a sur mon ecran ?"
        gets a description, "y a-t-il une erreur ?" gets answered
        specifically, rather than both getting the same generic summary.

        Same two-part shape as the other read-then-speak handlers: the
        narration Nemotron wrote *before* anything was captured, then the
        actual answer once a screenshot exists to ask about.
        """
        from heypeer.executor import screen

        self._speak(narration or _bilingual(
            language, "Je regarde l'écran...", "Let me look at the screen...",
        ), language=language)

        image_bytes = screen.capture()
        if image_bytes is None:
            self._speak(_bilingual(
                language, "Je n'ai pas pu capturer l'écran.", "I couldn't capture the screen.",
            ), language=language)
            return

        try:
            answer = self.nemotron.describe_image(image_bytes, question, language)
        except Exception as exc:
            self._log(f"Screen analysis failed: {exc}")
            answer = ""
        if answer:
            self._speak(answer, language=language)
        else:
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à analyser l'écran.",
                "I couldn't analyze the screen.",
            ), language=language)

    def _resolve_code_path(self, name_or_path: str) -> "Path | None":
        """Resolves `name_or_path` to a real file for `analyze_code`/
        `fix_code` - checked as a path in its own right first (absolute, or
        otherwise directly resolvable), then falling back to a bare
        filename inside the watched directory the same way every other
        file action resolves one.

        Unlike move/rename/delete, code actions are not confined to the
        watched directory by design: a coding task is about whatever file
        the user is actually working on, which is very unlikely to be
        ~/Downloads - "resume facture.pdf" is a watched-folder document,
        "corrige calc.py" is wherever the user's real project lives. Found
        live: the whole `analyze_code`/`fix_code` pair only ever worked for
        a file already in the watched folder, which is exactly why. This
        does mean there is no path-containment check the way file actions
        have one - the safety net here is undo-on-write (`fix_code`), not a
        directory boundary; see that handler's own docstring.
        """
        candidate = Path(name_or_path).expanduser()
        if candidate.is_file():
            return candidate
        if self.watched_dir is not None:
            resolved = resolve_existing_filename(self.watched_dir, name_or_path)
            if resolved:
                return self.watched_dir / resolved
        return None

    def _run_analyze_code(
        self, filename: str, question: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """Reads `filename` and asks Nemotron to diagnose it - nothing is
        changed. `question` is the user's own instruction text, so "pourquoi
        ca plante sur une liste vide ?" gets answered specifically rather
        than a generic review - see `NemotronClient.diagnose_code`."""
        path = self._resolve_code_path(filename)
        if path is None:
            self._speak(_bilingual(
                language, f"Je ne vois pas de fichier {filename}.",
                f"I can't find the file {filename}.",
            ), language=language)
            return

        try:
            code = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._log(f"Could not read {path}: {exc}")
            self._speak(_bilingual(
                language, f"Je n'ai pas pu lire {path.name}.", f"I couldn't read {path.name}.",
            ), language=language)
            return

        self._speak(narration or _bilingual(
            language, "Je regarde le code...", "Let me look at the code...",
        ), language=language)
        try:
            diagnosis = self.nemotron.diagnose_code(code, question, language)
        except Exception as exc:
            self._log(f"Code diagnosis failed: {exc}")
            diagnosis = ""
        if diagnosis:
            self._speak(diagnosis, language=language)
        else:
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à analyser ce code.",
                "I couldn't analyze that code.",
            ), language=language)

    def _run_fix_code(
        self, filename: str, question: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """Dispatches a real coding agent (`executor/coding_agent.py`) to
        edit `filename` - the one action here with no confirmation gate that
        genuinely writes code, not a filesystem move. The safety net is the
        same shape as everywhere else in this project: the file's original
        content is captured *before* the agent runs and pushed onto the
        undo stack, so "annule" restores it exactly, whatever the agent did.

        The agent runs with the file's own containing folder as its working
        directory (`_resolve_code_path`, unlike file actions, is not
        confined to the watched folder) - real project context (sibling
        files, a .git root) rather than an unrelated Downloads folder that
        happens to be watched.

        Only tracks the one file the user named - if the agent also touched
        others while working, those are not captured or undoable from here.
        Scoping the agent's own reach to just this file is a larger change
        (`--add-dir`-style restriction, or a fresh worktree per fix) not
        attempted in this round.
        """
        from heypeer.executor import coding_agent

        path = self._resolve_code_path(filename)
        if path is None:
            self._speak(_bilingual(
                language, f"Je ne vois pas de fichier {filename}.",
                f"I can't find the file {filename}.",
            ), language=language)
            return

        if not coding_agent.is_available():
            self._log("Coding agent unavailable: 'claude' not found on PATH.")
            self._speak(_bilingual(
                language,
                "Je ne peux pas corriger de code pour l'instant, l'agent de code "
                "n'est pas installé.",
                "I can't fix code right now, the coding agent isn't installed.",
            ), language=language)
            return

        try:
            original_content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._log(f"Could not read {path}: {exc}")
            self._speak(_bilingual(
                language, f"Je n'ai pas pu lire {path.name}.", f"I couldn't read {path.name}.",
            ), language=language)
            return

        self._speak(narration or _bilingual(
            language, "Je regarde le code, ça peut prendre un moment...",
            "Let me look at the code, this might take a moment...",
        ), language=language)

        prompt = (
            f"In the file {path}: {question}\n\n"
            "Explain briefly what was wrong, then fix it. Keep your final summary short."
        )
        self.tray.set_status(Status.EXECUTING)
        try:
            output = coding_agent.run(prompt, path.parent)
        except coding_agent.CodingAgentTimedOut:
            self._log("Coding agent timed out.")
            self._speak(_bilingual(
                language, "Ça prend trop de temps, j'abandonne.",
                "That's taking too long, I'm giving up.",
            ), language=language)
            return
        except Exception as exc:
            self._log(f"Coding agent failed: {exc}")
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à corriger le code.",
                "I couldn't fix the code.",
            ), language=language)
            return
        finally:
            self.tray.set_status(Status.LISTENING if self.tray.auto_mode else Status.OFF)

        new_content = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        if new_content is None or new_content == original_content:
            self._speak(_bilingual(
                language, f"Je n'ai rien changé dans {path.name}.",
                f"I didn't change anything in {path.name}.",
            ), language=language)
            return

        self._undo_stack.push(undo.code_fixed(path, original_content))

        import tempfile

        backup_path = Path(tempfile.gettempdir()) / f"heypeer_before_{path.name}"
        backup_path.write_text(original_content, encoding="utf-8")
        coding_agent.open_diff_in_vscode(backup_path, path)

        try:
            summary = self.nemotron.summarize_for_speech(output, language) if output else ""
        except Exception as exc:
            self._log(f"Summarizing the fix failed: {exc}")
            summary = ""
        self._speak(summary or _bilingual(
            language, f"J'ai corrigé {path.name}.", f"I fixed {path.name}.",
        ), language=language)

    def _run_debug_screen_code(
        self, question: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """Diagnoses code visible on screen with no filename needed at all
        - see `NemotronClient.diagnose_screen_code` and this project's own
        history for why: `analyze_code`/`fix_code` only ever worked for a
        file already in the watched folder (~/Downloads by default), which
        is nowhere near where an actual coding project lives. Looking at
        whatever is on screen - almost always an editor with the exact
        function being asked about open - sidesteps needing a name at all.

        Unlike every other read-then-speak handler in this file, this one
        leaves a follow-up window open: the diagnosis is written to end in
        a question ("veux-tu que je corrige ?"), so the natural answer -
        "oui", "corrige-le" - has to reach `fix_code` without repeating the
        wake word, the same way "ask" already does for a missing piece.
        If the diagnosis named a file, it is in this turn's own spoken
        text, which becomes part of the exchange history - Nemotron can
        refer back to it on the follow-up turn to fill `fix_code`'s
        `target_name`, the same way it already resolves one named earlier
        in a conversation for any other action.
        """
        from heypeer.executor import screen

        self._speak(narration or _bilingual(
            language, "Je regarde l'écran...", "Let me look at the screen...",
        ), language=language)

        image_bytes = screen.capture()
        if image_bytes is None:
            self._speak(_bilingual(
                language, "Je n'ai pas pu capturer l'écran.", "I couldn't capture the screen.",
            ), language=language)
            return

        try:
            diagnosis = self.nemotron.diagnose_screen_code(image_bytes, question, language)
        except Exception as exc:
            self._log(f"Screen code diagnosis failed: {exc}")
            diagnosis = ""
        if diagnosis:
            self._speak(diagnosis, language=language)
            self._arm_followup(CONVERSATION_WINDOW_SECONDS)
        else:
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à analyser le code à l'écran.",
                "I couldn't analyze the code on screen.",
            ), language=language)

    def _run_remember_fact(
        self, fact: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """Stores `fact` in `heypeer/memory.py`'s persistent store - true
        next week, on a fresh launch, not just for the rest of this
        exchange (see that module's docstring for why this is a separate
        store from `self._history`). A write failure (disk full, a
        permissions problem) must degrade to an honest spoken message
        rather than silently claiming to remember something it did not."""
        from heypeer import memory as memory_store

        try:
            memory_store.remember(fact)
        except OSError as exc:
            self._log(f"Could not save memory: {exc}")
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à enregistrer ça.",
                "I couldn't save that.",
            ), language=language)
            return
        self._speak(narration or _bilingual(
            language, "Je m'en souviendrai.", "I'll remember that.",
        ), language=language)

    def _run_general_task(
        self, task: str, narration: "str | None", language: str = "fr"
    ) -> None:
        """Dispatches `task` to Hermes Agent (`executor/general_agent.py`)
        for anything with no action of its own - open-ended web research,
        scheduling, and the like. See that module's docstring for why this
        has no undo entry the way `fix_code` does: an open-ended task is
        not reliably one reversible edit, so there is nothing honest to
        capture as "the" change to restore.
        """
        from heypeer.executor import general_agent

        if not general_agent.is_available():
            self._log("General agent unavailable: 'hermes' not found on PATH.")
            self._speak(_bilingual(
                language,
                "Je ne peux pas faire de tâche générale pour l'instant, l'agent "
                "n'est pas installé.",
                "I can't handle general tasks right now, the agent isn't installed.",
            ), language=language)
            return

        self._speak(narration or _bilingual(
            language, "Je m'en occupe, ça peut prendre un moment...",
            "I'm on it, this might take a moment...",
        ), language=language)

        self.tray.set_status(Status.EXECUTING)
        try:
            output = general_agent.run(task, self.watched_dir or Path.home())
        except general_agent.GeneralAgentTimedOut:
            self._log("General agent timed out.")
            self._speak(_bilingual(
                language, "Ça prend trop de temps, j'abandonne.",
                "That's taking too long, I'm giving up.",
            ), language=language)
            return
        except Exception as exc:
            self._log(f"General agent failed: {exc}")
            self._speak(_bilingual(
                language, "Je n'ai pas réussi à faire cette tâche.",
                "I couldn't complete that task.",
            ), language=language)
            return
        finally:
            self.tray.set_status(Status.LISTENING if self.tray.auto_mode else Status.OFF)

        try:
            summary = self.nemotron.summarize_for_speech(output, language) if output else ""
        except Exception as exc:
            self._log(f"Summarizing the task result failed: {exc}")
            summary = ""
        self._speak(summary or _bilingual(
            language, "C'est fait.", "Done.",
        ), language=language)

    def _resolved_path(self, spoken_name: str) -> "Path | None":
        """Where a spoken filename actually points, resolved *before* the
        action runs — afterwards the file has moved or been renamed and the
        original path can no longer be recovered, which is what undo needs."""
        if self.watched_dir is None:
            return None
        resolved = resolve_existing_filename(self.watched_dir, spoken_name)
        return self.watched_dir / resolved if resolved else None

    def _run_undo(self, language: str = "fr") -> None:
        """`entry.description` (and `not_undoable_reason`) are always
        written in French - see `executor/undo.py` - regardless of which
        language the *original* action or this "annule"/"undo" request used.
        Fixing that needs the original action's language stored alongside
        the description at the time it was pushed, which nothing does yet;
        this narrates Hey Peer's own fixed half of the sentence in
        `language` and leaves the embedded description as-is rather than
        pretending to a precision this does not have.
        """
        entry = self._undo_stack.pop()
        if entry is None:
            self._log("Nothing to undo.")
            self._speak(_bilingual(language, "Il n'y a rien à annuler.", "There's nothing to undo."),
                       language=language)
            return
        if entry.undo is None:
            self._log(f"Not undoable: {entry.description} ({entry.not_undoable_reason})")
            self._speak(_bilingual(
                language, f"Je ne peux pas annuler ça : {entry.not_undoable_reason}.",
                f"I can't undo that: {entry.not_undoable_reason}.",
            ), language=language)
            return

        self._speak_async(_bilingual(language, f"J'annule {entry.description}.",
                                     f"Undoing {entry.description}."), language=language)
        try:
            entry.undo()
            self._log(f"Undone: {entry.description}.")
            self._arm_followup()
        except Exception as exc:
            self._log(f"Undo failed: {exc}")
            self._speak(_bilingual(language, "Je n'ai pas réussi à annuler.",
                                   "I couldn't undo that."), language=language)

    def _run_file_action(
        self,
        narration: str,
        run: "Callable[[], Path]",
        done: "Callable[[Path], str]",
        undo_factory: "Callable[[Path], undo.UndoEntry] | None" = None,
        language: str = "fr",
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

        self._speak_async(narration, language=language)
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
            self._speak(_bilingual(language, "Je n'ai pas pu faire ça, quelque chose semblait anormal.",
                                   "I couldn't do that - something looked wrong."), language=language)
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
