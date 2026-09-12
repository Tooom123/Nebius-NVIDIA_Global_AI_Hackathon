"""Real-time "Hey Peer" wake-word detection.

Runs entirely on-device: audio never leaves the machine unless the classifier
fires above `threshold`. Uses the same openWakeWord melspectrogram + embedding
pipeline as `train.py`, feeding a rolling window of the last `CLIP_SECONDS` of
microphone audio into the custom classifier head produced by that script.

Scoring uses `AudioFeatures`'s own incremental streaming API
(`_streaming_features`/`get_features`, exposed via `__call__`) rather than
calling `embed_clips()` on the whole rolling window every chunk. The first
version of this listener did the latter — recomputing the melspectrogram and
embeddings for the entire ~1.5s window on every single 80ms chunk — which is
exactly the "reprocess everything, constantly" pattern real always-listening
wake-word engines (Hey Siri, Alexa, OK Google) specifically avoid. The
streaming API only processes the newest samples each call and keeps a
rolling feature buffer internally, cutting the per-chunk work roughly to the
size of one chunk instead of the size of the whole detection window.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from heypeer.paths import resource, user_data

import numpy as np
import onnxruntime as ort
import openwakeword
from openwakeword.utils import AudioFeatures

SAMPLE_RATE = 16000
CLIP_SECONDS = 1.5
CHUNK_SAMPLES = 1280  # 80ms chunks, openWakeWord's standard streaming granularity
COOLDOWN_SECONDS = 1.5  # minimum gap between two separate detections

# Enough real chunks to fully flush openWakeWord's synthetic-silence seed
# (see `_prime_feature_buffer`) out of the scoring window - one CLIP_SECONDS'
# worth, rounded up so the window is never partly stale.
PRIMING_CHUNKS = math.ceil(CLIP_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

# Simple energy-based end-pointing for the instruction recorded right after a
# wake-word trigger — good enough for a spoken command a few seconds long
# without pulling in a separate VAD model.
INSTRUCTION_MAX_SECONDS = 8.0
# ~1.2s of trailing silence ends the recording. Was ~0.8s, which cut real
# instructions off mid-sentence on the user's hardware ("déplace le fichier
# 4.0.", "Déplace le fichier 4.txt-"): people pause naturally between a
# filename and a destination, and that pause was being read as "done".
INSTRUCTION_SILENCE_CHUNKS = 15
INSTRUCTION_MIN_SPEECH_CHUNKS = 3

# End-pointing is adaptive from here on, between these two bounds, instead
# of always waiting the full `INSTRUCTION_SILENCE_CHUNKS`.
#
# The fixed wait is what users describe as an assistant that "doesn't know
# when I've finished talking" - reported as sluggishness, though it is
# really a turn-taking problem. It cannot be fixed by lowering the constant:
# the reason it is 15 and not 10 is a real bug where "deplace le fichier
# 4.0." was cut off mid-sentence, because people pause between a filename
# and a destination. Both failures are real and they pull opposite ways.
#
# What separates them is not how long the pause is but where it happens. A
# pause after a short, complete-sounding burst is usually the end of the
# turn; a pause after a long or still-rising one is usually mid-sentence.
# So the wait is short by default and stretched when the audio just before
# the pause looks like someone still going.
INSTRUCTION_SILENCE_CHUNKS_MIN = 9   # ~0.7s, when the turn sounds finished
INSTRUCTION_SILENCE_CHUNKS_MAX = 19  # ~1.5s, when it sounds mid-sentence
# A burst longer than this suggests a sentence still in progress rather
# than a short command - "deplace le fichier facture de mars" pausing
# before "vers Archives", as opposed to "annule" being simply done.
LONG_UTTERANCE_CHUNKS = 12  # ~1s of speech before the pause
# Never end-point before this much audio, regardless of silence — protects
# against a slow start (a breath, a pause for thought) truncating the whole
# instruction to nothing.
INSTRUCTION_MIN_SECONDS = 1.2

# Speech is detected relative to the room's own noise floor rather than at a
# fixed level. A fixed -40 dBFS threshold assumes one particular mic gain and
# room: too high and a quiet speaker never registers, too low and every fan
# or keyboard click counts as speech. `SPEECH_MARGIN_DB` above the measured
# floor is what actually separates "someone is talking" from "the room".
SPEECH_MARGIN_DB = 12.0
# Bounds keep the adaptive threshold sane if calibration lands somewhere odd
# (a muted mic reads ~-90 dBFS; a very loud room could otherwise push the
# threshold above normal speech).
SPEECH_THRESHOLD_MIN_DBFS = -55.0
SPEECH_THRESHOLD_MAX_DBFS = -25.0
# Fallback for the very first detection, before any noise floor is measured.
SPEECH_DBFS_THRESHOLD = -40.0


# A keystroke is a click: almost all of its energy arrives in one or two
# chunks and is gone. Speech is not - "Hey Peer" is a syllable and a half,
# sustained across many chunks. So a trigger whose surrounding audio is a
# single spike is a keyboard, a door, a cup on a desk; a trigger surrounded
# by sustained energy is a voice.
#
# This is not a general noise filter and is not meant to be. It rejects
# exactly the shape the user reported - typing setting Hey Peer off - and
# leaves everything else to the second-stage transcript check.
IMPULSE_MIN_LOUD_CHUNKS = 3
IMPULSE_MARGIN_DB = 9.0


def looks_like_speech(chunks: "list[np.ndarray]", noise_floor_dbfs: float) -> bool:
    """Whether the audio around a trigger has the shape of speech rather
    than of a single impulse.

    `chunks` is the prebuffer - the couple of seconds up to and including
    the trigger. Returns True when at least `IMPULSE_MIN_LOUD_CHUNKS` of
    them are clearly above the room's floor, which a keystroke never
    manages and a spoken wake word always does.
    """
    if not chunks:
        return True  # nothing to judge on; let the transcript check decide

    levels = [chunk_dbfs(chunk) for chunk in chunks]
    # Measured against the *peak*, not the noise floor. Against the floor
    # this rejected continuously loud audio, because when every chunk is
    # loud the floor is that level and nothing clears it - a real defect
    # found by the existing tests, whose fake microphone is exactly that
    # case. What actually distinguishes a keystroke is that its energy is
    # concentrated in a couple of chunks *relative to its own peak*.
    peak = max(levels)
    loud = sum(1 for level in levels if level > peak - IMPULSE_MARGIN_DB)
    return loud >= IMPULSE_MIN_LOUD_CHUNKS


def speech_threshold_dbfs(noise_floor_dbfs: float) -> float:
    """Speech/silence cutoff for a room whose measured noise floor is
    `noise_floor_dbfs`, clamped to a sane range."""
    return max(
        SPEECH_THRESHOLD_MIN_DBFS,
        min(SPEECH_THRESHOLD_MAX_DBFS, noise_floor_dbfs + SPEECH_MARGIN_DB),
    )


def silence_chunks_needed(speech_chunks_before_pause: int, trailing_off: bool) -> int:
    """How much trailing silence should end the turn, given what the user
    was doing right before it went quiet.

    `speech_chunks_before_pause` is the length of the burst that just
    ended; `trailing_off` says whether it was getting quieter, the way a
    sentence closes, rather than holding level the way a mid-sentence
    breath does.

    Returns a number of chunks between `INSTRUCTION_SILENCE_CHUNKS_MIN` and
    `INSTRUCTION_SILENCE_CHUNKS_MAX`. Being wrong in the two directions is
    not symmetric: waiting too long makes Hey Peer feel slow, waiting too
    little truncates the instruction and loses what the user said. So the
    short wait is only used when the evidence for "finished" is positive -
    a short burst that trailed off - and anything ambiguous keeps the
    patient behaviour that fixed the original truncation bug.
    """
    if speech_chunks_before_pause >= LONG_UTTERANCE_CHUNKS:
        return INSTRUCTION_SILENCE_CHUNKS_MAX
    if trailing_off:
        return INSTRUCTION_SILENCE_CHUNKS_MIN
    return INSTRUCTION_SILENCE_CHUNKS


def estimate_noise_floor(chunks: "list[np.ndarray]") -> float:
    """Estimates the ambient noise floor from recent audio, as the 20th
    percentile of per-chunk levels — a low percentile rather than the
    minimum (robust to one freak-quiet chunk) and rather than the mean
    (which speech in the same window would drag upward)."""
    if not chunks:
        return SPEECH_DBFS_THRESHOLD - SPEECH_MARGIN_DB
    levels = [chunk_dbfs(c) for c in chunks]
    return float(np.percentile(levels, 20))

# How much audio from *before* a trigger to keep and hand to the verifier.
# Detection fires at the end of the spoken phrase, so the wake word lives
# entirely in this window — 2s covers "Hey Peer" plus lead-in comfortably.
PREBUFFER_SECONDS = 2.0
PREBUFFER_CHUNKS = int(PREBUFFER_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

# After Hey Peer finishes acting, it stays open this long for a follow-up
# command that needs no wake word at all — the natural way a conversation
# continues. Kept short on purpose: during this window ordinary speech in
# the room can start a turn, since there is no wake word to verify against.
# The instruction still has to resolve to a concrete file action, so stray
# conversation resolves to "unknown" and does nothing.
FOLLOWUP_WINDOW_SECONDS = 6.0
# Speech has to clear the room's noise floor by this much to open a
# follow-up turn — stricter than ordinary end-pointing, because here it is
# deciding whether to start listening at all rather than whether someone is
# still talking.
FOLLOWUP_MARGIN_DB = 6.0


def _ensure_openwakeword_models() -> None:
    """openWakeWord's melspectrogram/embedding ONNX models are bundled in
    some package versions but not others (0.6.0's wheel is ~60 KB — clearly
    not including them; a version pinned only as ">=0.4.0" can land either
    way depending on when/where `pip install` runs). Rather than pin an
    exact version and hope, check for the files openWakeWord itself expects
    by default and download them on the spot if missing — this is exactly
    what surfaced as a raw onnxruntime NoSuchFile traceback on a fresh
    Windows install after this project's own AudioFeatures() call.
    """
    models_dir = Path(openwakeword.__file__).parent / "resources" / "models"
    required = [models_dir / "melspectrogram.onnx", models_dir / "embedding_model.onnx"]
    if all(p.exists() for p in required):
        return

    from openwakeword.utils import download_models

    print(
        "[wakeword] Modeles openWakeWord manquants (melspectrogram/embedding) - "
        "telechargement en cours..."
    )
    # A model name that matches nothing skips downloading the large bundle of
    # official pretrained wake words (alexa, hey_jarvis, ...) we don't use —
    # download_models() unconditionally fetches melspec/embedding/VAD first
    # regardless of model_names, which is all we actually need here.
    download_models(model_names=["__heypeer_placeholder_no_match__"])


def chunk_dbfs(chunk: np.ndarray) -> float:
    """RMS level of an int16 PCM chunk in dBFS (0 = full scale, more negative =
    quieter; silence/no signal reads around -90 or lower)."""
    if len(chunk) == 0:
        return -120.0
    rms = np.sqrt(np.mean(chunk.astype(np.float64) ** 2))
    return float(20 * np.log10(rms / 32768 + 1e-9))


def dbfs_to_level(dbfs: float) -> float:
    """Normalizes dBFS to a 0-1 range for the UI's audio-reactive circle
    (same -60..0 dBFS window the console debug meter already uses)."""
    return max(0.0, min(1.0, (dbfs + 60) / 60))


def save_wav(audio: np.ndarray, path) -> None:
    """Writes recorded int16 mono PCM audio to a 16kHz wav file."""
    import soundfile as sf

    sf.write(str(path), audio, SAMPLE_RATE, subtype="PCM_16")


CHIME_PATH = resource("heypeer", "assets", "activation_chime.wav")  # ships with the app

_chime_audio: "np.ndarray | None" = None


def _load_chime() -> np.ndarray:
    """Loads (and caches) the activation chime. Shipped as a pre-decoded
    16kHz mono WAV rather than the original mp3 the user supplied: decoding
    mp3 needs libsndfile >= 1.1, which isn't guaranteed on every install,
    and this keeps playback on the same int16/pyaudio path as the rest of
    the audio pipeline."""
    global _chime_audio
    if _chime_audio is None:
        import soundfile as sf

        data, _sr = sf.read(str(CHIME_PATH), dtype="int16")
        _chime_audio = data if data.ndim == 1 else data.mean(axis=1).astype(np.int16)
    return _chime_audio


def play_activation_chime(blocking: bool = False) -> None:
    """Plays the activation chime the instant the wake word triggers. The
    user reported not being sure whether Hey Peer had actually heard them; a
    near-instant audible cue (far faster than speaking a full sentence via
    Piper) gives that confirmation the same way real voice assistants do.

    `blocking=True` when the chime is the "speak now" cue itself: recording
    must not start until it has finished, or the mic records the beep. The
    asset is trimmed short (~0.3s) precisely so that wait is barely felt.
    """
    if blocking:
        _play_chime_blocking()
    else:
        threading.Thread(target=_play_chime_blocking, daemon=True).start()


def _play_chime_blocking() -> None:
    from heypeer.tray import audio_out

    audio_out.play(_load_chime().tobytes(), rate=SAMPLE_RATE)


class WakeWordListener:
    """Listens to the microphone and calls `on_detected` when "Hey Peer" is heard."""

    def __init__(self, model_path: str, threshold: float = 0.5, debug: bool = False) -> None:
        self.model_path = model_path
        self.threshold = threshold
        # TEMPORARY: prints a live dB meter + score per chunk, and the input
        # device name at startup, so mic hardware issues are obvious instead
        # of "nothing happens, no idea why". Remove/gate more permanently
        # once real wake-word detection is validated on real hardware.
        self.debug = debug
        _ensure_openwakeword_models()
        self._features = AudioFeatures()
        self._session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        # Number of embedding frames that add up to CLIP_SECONDS — matches
        # what train.py's embed_clips()/.mean(axis=1) produced per training
        # clip, so streaming scoring stays consistent with what the
        # classifier actually learned.
        self._n_feature_frames = self._features.get_embedding_shape(CLIP_SECONDS)[0]
        self._running = False
        self._debug_print_counter = 0
        # A single utterance of "Hey Peer" keeps the score above threshold
        # for several consecutive chunks (it's a plateau, not a single
        # spike) -- without debouncing, on_detected() fired once per chunk
        # in that plateau, i.e. several times for one utterance. Only fire
        # on the rising edge (was below, now above), and refuse to fire
        # again within COOLDOWN_SECONDS regardless, as a backstop.
        self._armed = True
        self._last_trigger_time = 0.0
        # Muted while Hey Peer's own TTS is speaking (see main.py's `_speak`)
        # so its own voice bleeding back into the mic — a real issue with
        # some headsets — can't be scored or false-trigger the wake word.
        # Not true acoustic echo cancellation (no cancellation happens *during*
        # simultaneous playback+speech), but Hey Peer never needs to listen
        # for the wake word while it's actively talking anyway, so gating
        # fully covers the "hears itself" symptom this was meant to fix.
        self._muted = False
        # Set by `mute_except_barge_in` - muted for turn-taking, but still
        # scoring so the wake word can interrupt playback. See that method.
        self._listen_for_barge_in = False
        # Called when the wake word fires while barge-in listening is on.
        # Set by whoever owns playback; None means nothing to interrupt.
        self.on_barge_in: "Callable[[], None] | None" = None
        # Rolling window of the most recent raw chunks, so the audio that
        # *caused* a detection (the wake word itself) can be handed to the
        # second-stage verifier along with the instruction — see
        # heypeer/wakeword/verify.py. Detection fires at the end of the
        # phrase, so without this the wake word is already gone by the time
        # recording starts.
        self._prebuffer: deque = deque(maxlen=PREBUFFER_CHUNKS)
        # Timestamp until which speech alone (no wake word) starts a turn.
        self._followup_until = 0.0

    def arm_followup(self, seconds: float = FOLLOWUP_WINDOW_SECONDS) -> None:
        """Opens a short window during which speech alone starts a turn, so
        the user can chain a second command without repeating the wake
        word."""
        self._followup_until = time.time() + seconds

    def cancel_followup(self) -> None:
        self._followup_until = 0.0

    def _followup_open(self) -> bool:
        return time.time() < self._followup_until

    def mute(self) -> None:
        self._muted = True
        self._listen_for_barge_in = False

    def mute_except_barge_in(self) -> None:
        """Mutes ordinary turn-taking but keeps scoring the wake word, so
        saying "Hey Peer" over the top of a spoken answer can cut it off.

        This is the one case the plain `mute` above cannot serve. Its
        comment reasons that Hey Peer "never needs to listen for the wake
        word while it's actively talking anyway" - true for starting a
        turn, and exactly wrong for stopping one. The echo concern that
        motivated muting is still real, so this deliberately does *not*
        re-open the ordinary path: a detection here only interrupts, it
        never starts a turn from whatever the microphone picked up
        alongside Hey Peer's own voice.
        """
        self._muted = True
        self._listen_for_barge_in = True

    def unmute(self) -> None:
        """Re-arms as well as unmuting, so a new "Hey Peer" can follow
        immediately after a turn. Without the explicit re-arm the listener
        waited for the score to fall below the threshold on its own, which
        made chaining two commands feel broken."""
        self._muted = False
        self._listen_for_barge_in = False
        self._armed = True
        self._last_trigger_time = 0.0
        self._prebuffer.clear()

    def _maybe_trigger(self, score: float) -> bool:
        """Returns True at most once per utterance (rising edge + cooldown)."""
        if score < self.threshold:
            self._armed = True
            return False
        if not self._armed:
            return False
        if time.time() - self._last_trigger_time < COOLDOWN_SECONDS:
            return False
        self._armed = False
        self._last_trigger_time = time.time()
        return True

    def _score(self) -> float:
        features = self._features.get_features(n_feature_frames=self._n_feature_frames)
        embedding = features.mean(axis=1)
        probs = self._session.run(None, {self._input_name: embedding.astype(np.float32)})[1]
        return float(probs[0][1])

    def process_chunk(self, chunk: np.ndarray) -> float:
        """Feed one int16 PCM chunk (>= CHUNK_SAMPLES); incrementally updates
        openWakeWord's internal streaming feature buffer and returns the
        current detection score."""
        self._features(chunk)
        return self._score()

    def _prime_feature_buffer(self, stream) -> None:
        """Reads `PRIMING_CHUNKS` of real microphone audio and feeds it into
        the streaming feature buffer, before scoring anything for real.

        openWakeWord's `AudioFeatures` seeds `feature_buffer` at construction
        by running the embedding model over ten seconds of pure silence
        (`self.feature_buffer = self._get_embeddings(np.zeros(160000))` in
        its own source - "fill with blank data to start"). `_score()` looks
        at the most recent `CLIP_SECONDS` of that buffer, so for the first
        `CLIP_SECONDS` of real listening, the window it scores is a mix of
        real embeddings and that synthetic-silence seed - nothing like the
        plain `CLIP_SECONDS` of real speech `train.py` actually trained on.

        Found from a report that repeated after round 25's fix for a
        different cold-start gap (Whisper's *verifier* model loading):
        "le premier Hey Peer est souvent rate, le bit avant que le blob
        descende". This is the detector itself, independent of that earlier
        fix - not necessarily scoring low, but scoring against a window the
        classifier never saw anything like in training, so its answer
        either way (trigger or not) can't be trusted. The fix isn't "raise
        the score" - it's refusing to let `_maybe_trigger` decide anything
        from that window at all: no callback fires until the mix is fully
        flushed by real audio, which the mic supplies on its own as
        ordinary room tone before anyone has spoken.

        This close to microphone hardware and openWakeWord's own internals,
        a synthetic tone-vs-noise toy classifier (see the test suite) can
        confirm the *mechanism* - priming reads and discards, never scores,
        never calls back - but not that this measurably fixes the reported
        miss on a real voice against the real trained model; that needs
        the user's own hardware, the same as every other wake-word change
        in this project.
        """
        for _ in range(PRIMING_CHUNKS):
            if not self._running:
                # stop() during priming - same as the main loop, priming has
                # to notice rather than block shutdown for up to CLIP_SECONDS.
                return
            raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            self._features(np.frombuffer(raw, dtype=np.int16))

    def _record_instruction(
        self,
        stream,
        on_level: "Callable[[float, bool], None] | None" = None,
        noise_floor_dbfs: "float | None" = None,
    ) -> np.ndarray:
        """Records audio right after a wake-word trigger, on the same open
        mic stream, until the user stops talking or a max-duration safety
        cap is hit. Wake-word scoring is paused for this stretch — it's
        the instruction being captured, not more "Hey Peer"s to detect.

        End-pointing reads the level relative to the room's own noise floor
        (measured from the prebuffer, which is real audio from the seconds
        just before the user started speaking) rather than a fixed dBFS
        cutoff — see `speech_threshold_dbfs`."""
        # `noise_floor_dbfs` is measured by the caller *before* it clears the
        # prebuffer. Measuring it here instead — which is what this used to do
        # — always saw an empty buffer and silently fell back to a fixed
        # cutoff, so the adaptive threshold never actually adapted. A speaker
        # quieter than that fixed value had the end of every sentence treated
        # as silence.
        if noise_floor_dbfs is None:
            noise_floor_dbfs = estimate_noise_floor(list(self._prebuffer))
        threshold = speech_threshold_dbfs(noise_floor_dbfs)
        frames = []
        speech_started = False
        speech_chunks = 0
        quiet_run = 0
        # Length of the run of speech that the current pause interrupted,
        # and the levels of its last chunks - together these are what the
        # adaptive wait is decided from. See `silence_chunks_needed`.
        current_burst = 0
        burst_at_pause = 0
        recent_levels: "list[float]" = []
        levels_at_pause: "list[float]" = []
        max_chunks = int(INSTRUCTION_MAX_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)
        min_chunks = int(INSTRUCTION_MIN_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)
        for i in range(max_chunks):
            raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            chunk = np.frombuffer(raw, dtype=np.int16)
            frames.append(chunk)
            dbfs = chunk_dbfs(chunk)
            if on_level is not None:
                on_level(dbfs_to_level(dbfs), True)
            if dbfs > threshold:
                speech_started = True
                speech_chunks += 1
                current_burst += 1
                recent_levels.append(dbfs)
                del recent_levels[:-4]  # only the tail of the burst matters
                quiet_run = 0
            elif speech_started:
                if quiet_run == 0:
                    # First quiet chunk: freeze what the burst looked like,
                    # before `current_burst` is reset for the next one.
                    burst_at_pause = current_burst
                    levels_at_pause = list(recent_levels)
                    current_burst = 0
                    recent_levels = []
                quiet_run += 1
            # A sentence closes by trailing off; a mid-sentence breath does
            # not. Two chunks are enough to see which - more would need the
            # burst to be long, which is already the other signal.
            trailing_off = len(levels_at_pause) >= 2 and levels_at_pause[-1] < levels_at_pause[0]
            if (
                i + 1 >= min_chunks
                and speech_started
                and speech_chunks >= INSTRUCTION_MIN_SPEECH_CHUNKS
                and quiet_run >= silence_chunks_needed(burst_at_pause, trailing_off)
            ):
                break
        # The trailing quiet is deliberately kept. Trimming it saved ~0.1s of
        # transcription and cost far more than that: "quiet" here means below
        # the speech threshold, and the end of a spoken sentence often trails
        # off below it while still being speech. Cutting there truncated real
        # instructions ("Deplace le fichier 15-"), which is a much worse
        # failure than a fraction of a second of extra Whisper input.
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)

    def start(
        self,
        on_detected: "Callable[[np.ndarray, bool], None]",
        on_level: "Callable[[float, bool], None] | None" = None,
        on_verify: "Callable[[np.ndarray], bool] | None" = None,
        on_ready: "Callable[[], None] | None" = None,
    ) -> None:
        """`on_level(level, recording)` — level normalized 0-1 (see
        `dbfs_to_level`), `recording` True while capturing the instruction
        after a trigger, False while just scanning for the wake word. Meant
        to drive a live audio-reactive UI element; optional.

        `on_detected(audio, followup)` receives the captured turn; `followup`
        is True when it started from speech during a follow-up window rather
        than from a wake word, so the handler knows not to expect one in the
        transcript.

        `on_verify(pre_trigger_audio)` decides whether a detection was real,
        given the ~2s of audio containing the wake word itself. It runs on
        its own thread while the instruction is being recorded, and is where
        any user-visible reaction to a detection belongs (chime, indicator)
        — the raw detector fires on plenty of ordinary speech, so reacting
        before this confirms would surface every false positive. Returning
        Returning False suppresses the turn entirely. Optional; without it
        every trigger is treated as genuine.

        `on_ready()` runs after `on_verify` succeeds and immediately before
        recording begins, so anything it does - waiting for an indicator to
        finish appearing, then chiming - lands exactly on "speak now" and is
        over before the mic opens. It is the callback's job to decide how
        long to wait: this used to be a `ready_delay` argument slept here,
        but a fixed duration cannot know when something in another process
        has finished animating, and it was consistently too short."""
        import pyaudio

        self._running = True
        pa = pyaudio.PyAudio()
        if self.debug:
            try:
                info = pa.get_default_input_device_info()
                print(
                    f"[wakeword] Peripherique d'entree : {info['name']} "
                    f"(index {info['index']}, {int(info['defaultSampleRate'])} Hz natif)"
                )
            except Exception as exc:  # no default input device, permissions, etc.
                print(f"[wakeword] Impossible de lire le peripherique d'entree par defaut : {exc}")

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
        )
        if self.debug:
            print(f"[wakeword] Ecoute demarree (seuil de detection = {self.threshold}).")
        self._prime_feature_buffer(stream)
        try:
            while self._running:
                raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
                if self._muted:
                    if self._listen_for_barge_in:
                        # Score the real audio: the point of this mode is to
                        # hear "Hey Peer" spoken over the answer. A hit only
                        # stops playback - it deliberately does not start a
                        # turn, since what the mic is picking up right now
                        # includes Hey Peer's own voice.
                        chunk = np.frombuffer(raw, dtype=np.int16)
                        if self._maybe_trigger(self.process_chunk(chunk)):
                            if self.on_barge_in is not None:
                                self.on_barge_in()
                        continue
                    # Keep the streaming feature buffer moving, on silence
                    # rather than on the real (muted) audio. Skipping the
                    # update entirely — which is what this used to do — left
                    # the buffer holding the wake word that just fired: on
                    # unmute it still scored high, so `_maybe_trigger` never
                    # re-armed and a second "Hey Peer" was ignored for over a
                    # second. Feeding silence flushes it, so Hey Peer is ready
                    # again the moment the turn ends.
                    self.process_chunk(np.zeros(CHUNK_SAMPLES, dtype=np.int16))
                    continue
                chunk = np.frombuffer(raw, dtype=np.int16)
                self._prebuffer.append(chunk)
                score = self.process_chunk(chunk)
                dbfs = chunk_dbfs(chunk)
                if on_level is not None:
                    on_level(dbfs_to_level(dbfs), False)
                if self.debug:
                    # Printing (with a flush) every single 80ms chunk was
                    # measurably heavier on a slow terminal (Git Bash/MinTTY
                    # in particular) than the actual scoring work itself --
                    # every 3rd chunk (~240ms) still reads as live to a human
                    # eye and cuts that console I/O by two thirds.
                    self._debug_print_counter += 1
                    if self._debug_print_counter % 3 == 0:
                        bar_len = max(0, min(40, int(dbfs_to_level(dbfs) * 40)))
                        print(
                            f"\r[wakeword] {dbfs:6.1f} dBFS |{'#' * bar_len:<40}| "
                            f"score={score:.2f}   ",
                            end="",
                            flush=True,
                        )
                # A follow-up turn: speech alone, no wake word, for a short
                # window after Hey Peer has just acted. Checked before
                # wake-word scoring because there is nothing to score against
                # — the user is continuing a conversation, not starting one.
                if self._followup_open() and dbfs > speech_threshold_dbfs(
                    estimate_noise_floor(list(self._prebuffer))
                ) + FOLLOWUP_MARGIN_DB:
                    self.cancel_followup()
                    print("[wakeword] Suite (sans mot d'activation).")
                    noise_floor = estimate_noise_floor(list(self._prebuffer))
                    # Reject an impulse before anything else happens. A
                    # keystroke scoring above threshold is a real thing the
                    # user reported, and rejecting it here - rather than
                    # after transcription - means no chime, no blob, and no
                    # recording for something that was a key being pressed.
                    if not looks_like_speech(list(self._prebuffer), noise_floor):
                        if self.debug:
                            print(f"[wakeword] Impulsion ignoree (score={score:.2f}).")
                        self._prebuffer.clear()
                        continue
                    pre_audio = (
                        np.concatenate(list(self._prebuffer))
                        if self._prebuffer
                        else np.zeros(0, dtype=np.int16)
                    )
                    self._prebuffer.clear()
                    instruction_audio = self._record_instruction(
                        stream, on_level=on_level, noise_floor_dbfs=noise_floor
                    )
                    # No verification: there is no wake word in this audio by
                    # design, so `on_verify` would reject it. `followup=True`
                    # tells the handler the same thing.
                    on_detected(np.concatenate([pre_audio, instruction_audio]), True)
                    continue

                if self._maybe_trigger(score):
                    if self.debug:
                        print()  # move off the overwritten debug line
                        print(f"[wakeword] Candidat detecte (score={score:.2f}).")
                    # The prebuffer already holds the wake word (detection
                    # fires at the end of the phrase), so it can be verified
                    # right now — before any chime or on-screen reaction.
                    noise_floor = estimate_noise_floor(list(self._prebuffer))
                    # Reject an impulse before anything else happens. A
                    # keystroke scoring above threshold is a real thing the
                    # user reported, and rejecting it here - rather than
                    # after transcription - means no chime, no blob, and no
                    # recording for something that was a key being pressed.
                    if not looks_like_speech(list(self._prebuffer), noise_floor):
                        if self.debug:
                            print(f"[wakeword] Impulsion ignoree (score={score:.2f}).")
                        self._prebuffer.clear()
                        continue
                    pre_audio = (
                        np.concatenate(list(self._prebuffer))
                        if self._prebuffer
                        else np.zeros(0, dtype=np.int16)
                    )
                    self._prebuffer.clear()

                    # Verify *before* recording, not alongside it. Running
                    # them concurrently saved a few hundred milliseconds of
                    # audio, but it meant the chime and the indicator only
                    # appeared once recording was already well under way -
                    # so the user had usually finished speaking by the time
                    # the blob arrived, and it never appeared to react to
                    # their voice at all. Cue first, then listen, is both
                    # what the user asked for and how every assistant that
                    # feels responsive behaves.
                    try:
                        verified = on_verify(pre_audio) if on_verify is not None else True
                    except Exception as exc:
                        # A broken verifier (model missing, transcription
                        # error) must never make Hey Peer deaf - fall back to
                        # trusting the detector.
                        print(f"[wakeword] Verification failed, accepting: {exc}")
                        verified = True
                    if not verified:
                        if self.debug:
                            print("[wakeword] Rejete (pas de mot d'activation).")
                        continue

                    # Blocks for as long as the callback needs - it waits
                    # for the indicator to finish dropping in and then
                    # chimes, so the cue genuinely means "speak now".
                    if on_ready is not None:
                        on_ready()

                    instruction_audio = self._record_instruction(
                        stream, on_level=on_level, noise_floor_dbfs=noise_floor
                    )
                    print(
                        f"[wakeword] Instruction enregistree "
                        f"({len(instruction_audio) / SAMPLE_RATE:.1f}s)."
                    )
                    on_detected(np.concatenate([pre_audio, instruction_audio]), False)
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def stop(self) -> None:
        self._running = False


WAKEWORD_DIR = user_data("wakeword")  # the user trains their own model here
# A model trained on this machine's own voice. Gitignored, so it stays with
# the person who recorded it.
USER_MODEL_PATH = WAKEWORD_DIR / "hey_peer_user.onnx"
# The generic model shipped in the repository, trained on synthetic speech.
# Works for anyone, well for no one — a fresh clone has something that runs.
SHIPPED_MODEL_PATH = WAKEWORD_DIR / "hey_peer.onnx"


def default_model_path() -> Path:
    """The personalised model if this machine has one, else the shipped one.

    Kept as two files rather than one: training used to overwrite the
    committed generic model, which meant a personalised run silently changed
    a tracked file, and pulling or checking it out would clobber someone's
    own model. Preferring the personal one at load time gives both — a fresh
    clone still runs, and whoever records their voice gets their own model
    used automatically with nothing to configure.
    """
    return USER_MODEL_PATH if USER_MODEL_PATH.is_file() else SHIPPED_MODEL_PATH
