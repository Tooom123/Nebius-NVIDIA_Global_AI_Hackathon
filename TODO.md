# Hey Peer — build TODO

Working list for the hackathon build-out. Check off as each lands; commit + push after
each major implementation (per project convention).

- [x] Project scaffold: license, README, package skeleton, skill memory + test
- [x] Wake word "Hey Peer"
  - [x] Piper TTS sample-generation script (synthetic "Hey Peer" utterances)
  - [x] openWakeWord training script (embed → MLP classifier head → ONNX export),
        verified end-to-end with a synthetic tone-vs-noise fixture (no Piper
        voices available in this sandbox, so real "Hey Peer" audio wasn't
        generated here — script is ready to run once voices are downloaded)
  - [x] Real-time runtime listener (mic → openWakeWord embeddings → ONNX
        classifier → callback), `process_chunk` unit-tested; `start()`'s live
        mic loop needs real hardware to verify
- [x] Activity capture (minimal, scoped to one demo scenario)
  - [x] Cross-platform active app/window watcher (pywinctl)
  - [x] Mouse/keyboard event listener emitting `ActionEvent`s (pynput, no
        keystroke content), unit-tested for the focus-change logic; the live
        `start()` listener loop needs a real input device/WM to verify
- [x] Pattern detection + skill memory
  - [x] Sliding-window repeated-sequence detector (implement `PatternDetector.observe`)
  - [x] Wire detector output into `SkillMemory` (also fixed `SkillMemory` to
        actually (de)serialize `ActionEvent`s — it previously stored them
        raw, which would have broken once real actions were produced)
- [x] Nemotron 3 Nano Omni via Nebius Token Factory
  - [x] OpenAI-compatible client call (text-first, per plan step 4) — unit
        tested with a mocked OpenAI client, **and verified against the real
        Nebius API** once the user's API key + free hackathon credits were
        set up (correct id: `nvidia/Nemotron-3-Nano-Omni`, casing matters)
  - [x] Extend to audio clip + screenshot (omni input) — `interpret()` sends
        base64 audio + screenshot; unverified against the live API here
        (only `interpret_text()` has been exercised for real so far)
  - [x] Parse structured intent (`{action, skill_id, n_repetitions}`)
- [ ] Confirmation UI
  - [x] Minimal CLI confirm gate
  - [ ] (stretch) lightweight overlay if time allows
- [x] Automated execution
  - [x] `SkillRunner.run` replay via pyautogui — extended `ActionEvent` with
        replay metadata (click coords, key name, scroll delta); still never
        records literal typed characters, only special keys, so plain-char
        key presses correctly abort replay rather than guessing content
  - [x] Visual verification hook between steps (`verify_step` callback takes a
        screenshot and can abort the run — wiring an actual Nemotron-backed
        check happens in the demo-scenario step). Unit-tested with a stubbed
        `pyautogui`; unverified against a live display in this sandbox
- [x] Demo scenario — end-to-end wiring done in `heypeer/main.py`
  - [x] `HeyPeer` class wires capture -> detector -> memory, and on wake word:
        instruction -> Nemotron intent -> lookup skill -> confirm -> replay
        with Nemotron screen verification between steps. Unit-tested with
        mocked Nemotron/pyautogui/confirm (confirmed run, declined run, and
        unknown-intent paths all covered).
  - [x] Concrete demo scenario chosen: **file sorting** — moving files (e.g.
        PDFs) out of a watched folder (default `~/Downloads`) into another
        folder, repeated a few times, then "Hey Peer, do 4 more".
  - [x] File-move capture + replay, built specifically for this scenario:
        - `ActionType.FILE_MOVE` + `ActionEvent.src_path`/`dest_path` (still
          never records typed content — a file path isn't keystroke content)
        - `FileOpWatcher` (watchdog) emits a FILE_MOVE event straight from the
          OS's own move/rename notification — no click-coordinate guessing
        - `PatternDetector` groups FILE_MOVE events by (dest dir, extension)
          instead of literal filename, and allows a period-1 repeat (a single
          file move recurring) to count as a pattern — a repeat other event
          types intentionally ignore, since a single click/keypress recurring
          is usually noise
        - `SkillRunner` replays FILE_MOVE skills via `shutil.move` on the next
          N still-present files matching the same folder+extension, instead
          of pyautogui — robust to window position/state, unlike click replay
        - All unit-tested, including a real (non-mocked) file move observed
          through `watchdog` on this sandbox's filesystem
  - [x] **Full end-to-end rehearsal against the real Nebius API**: learned a
        3-repeat file-sorting skill from simulated FILE_MOVE events, said
        "fais-en 2 de plus", got back a correctly-resolved Intent from the
        live Nemotron endpoint, confirmed, and watched SkillRunner actually
        move the next 2 matching files via shutil. First-try success.
  - [ ] Wire real audio capture + screenshotting for `on_wake_word` (currently
        takes typed text as an instruction stand-in, per the plan's
        "text first" validation step) and swap in `NemotronClient.interpret`
  - [ ] Rehearse the full flow on a real machine with a Downloads-like folder,
        a real mic, and a real screen
- [x] Background app / hidden-icons tray + auto-mode toggle + status
  - [x] `heypeer/tray/app.py` — `TrayApp` wraps `pystray.Icon`: a "Mode auto"
        menu toggle arms/disarms the whole capture+wake-word pipeline, and a
        disabled menu item always shows the current status text. Icon color
        encodes status too (gray=off, green=listening, blue=executing,
        red=error). Unit-tested (menu state, toggle callback, status
        updates) — pystray's Icon constructs fine headless in this sandbox
        (X11 backend) but its real on-screen tray/menu-bar appearance is
        unverified.
  - [x] `heypeer/tray/cursor.py` — `CursorIndicator.set_active()` swaps the
        system cursor to a tinted arrow while auto mode is on. **Windows
        only** for now (`SetSystemCursor` win32 API + a generated `.cur`
        file with a PNG-encoded frame); macOS/Linux log a clear "not
        supported" message and no-op rather than silently doing nothing.
        The win32 call sequence is unit-tested with a mocked `ctypes.windll`;
        the actual on-screen result has never been seen on real Windows.
  - [x] `heypeer/main.py` restructured: `run_tray()` (new default) blocks the
        main thread on the tray's event loop while the capture
        watchers/wake-word listener start in a background thread once "Mode
        auto" is toggled on; `run_cli()` keeps the old always-on foreground
        console loop for headless dev boxes (`python -m heypeer.main --cli`).
  - [x] Fixed two real bugs found while smoke-testing this by hand: an empty
        `HEYPEER_WATCHED_DIR=` in `.env` was resolving to `.` instead of the
        documented default, and toggling auto mode with a missing watched
        directory used to crash the whole toggle instead of just skipping
        file-move detection for that session.
- [x] Bugs found on the user's real Windows machine (first real hardware
      test), fixed 2026-08-29:
  - [x] **Detector cross-contamination**: `ActivityWatcher` (clicks/keys) and
        `FileOpWatcher` (file moves) fed the *same* `PatternDetector`, so
        mouse activity during a real drag-and-drop could spuriously
        "complete" an unrelated click-based pattern, clearing the buffer and
        producing a bogus skill that replayed stale click coordinates and
        did nothing visible. Fixed by giving `HeyPeer` two independent
        detectors (`detector` for input events, `file_detector` for file
        moves) — regression-tested in `test_main.py`.
  - [x] **Cursor shape**: the hand-drawn arrow polygon looked wrong on real
        Windows. Replaced with `_extract_recolored_arrow()`, which reads
        Windows' own default arrow cursor bitmap via `GetIconInfo`/
        `GetDIBits` and recolors only its white fill pixels — exact shape,
        outline, and hotspot preserved, only the color changes. Per the
        user's request, cursor *shape* work stops here; only color changes
        for now.
  - [x] **Cursor never reset on quit**: `_stop_pipeline()` (called by the
        tray's "Quitter") never reset the cursor at all — real bug, not just
        a crash-recovery gap. Fixed: `_stop_pipeline` now calls
        `cursor.reset()`. Also added a defensive `cursor.reset()` at
        `HeyPeer` construction (clears a stale override left by a previous
        crashed run) and `atexit.register(peer.cursor.reset)` in both entry
        points, as defense-in-depth for exits Python can still catch.
        `CursorIndicator.reset()` is new — unlike `set_active(False)`, it's
        unconditional, not gated on the instance having seen `active=True`.
  - [x] Documented (not "fixed", since it's a platform limitation): Ctrl+C
        can't reliably interrupt pystray's native Windows message loop — the
        tray menu's "Quitter" is the reliable way to exit. Gave the user an
        immediate manual PowerShell one-liner to reset a stuck cursor
        independent of the app's state.
- [x] "Pure logic" direct file moves — no learned skill required
  - [x] `Intent` gained `src_filename`/`dest_folder` fields and a `move_file`
        action; `NemotronClient.interpret_text` now accepts an optional
        `watched_files` listing so Nemotron can ground "the file X" against
        real filenames instead of guessing one.
  - [x] `move_single_file()` (executor) performs the actual move; destination
        is always resolved as a subfolder *of the watched directory* (created
        if needed) — a deliberate safety constraint so a hallucinated or
        ambiguous destination can't write outside it. Still goes through the
        same `confirm()` gate as skill replay — no exception to "confirm
        before acting".
  - [x] Verified against the live Nebius API: "déplace le fichier facture
        vers Archives" correctly resolved `facture_mars.pdf` out of a listing
        that also contained `notes.txt`/`photo.jpg`, and the file actually
        moved on disk in an end-to-end (non-mocked) run.
- [x] Tray "Demander à Hey Peer..." prompt for debugging without a mic
  - [x] `heypeer/tray/prompt.py` opens a native tkinter text-input dialog;
        wired into `TrayApp` as a new menu item and into `HeyPeer` so typed
        text goes through the exact same `_handle_instruction()` path as a
        real wake-word activation. Unit-tested with the dialog mocked; the
        real on-screen dialog is unverified in this sandbox.
- [x] Round 2 of real-Windows bugs, fixed 2026-08-29:
  - [x] **Cursor extraction crash**: `OverflowError: int too long to convert`
        inside `GetObjectW`/`DeleteObject`. Root cause: none of the win32
        function calls had `argtypes`/`restype` declared, so ctypes defaulted
        handle arguments/return values to 32-bit `c_int` — silently
        truncating real 64-bit pointers, which raises the moment a handle's
        value happens to exceed 2**31 (routine for heap addresses on 64-bit
        Windows). Fixed by explicitly declaring `argtypes`/`restype` (via
        `ctypes.wintypes`) on every win32 entry point used
        (`LoadCursorW`, `GetIconInfo`, `GetObjectW`, `GetDC`/`ReleaseDC`,
        `GetDIBits`, `DeleteObject`, `LoadCursorFromFileW`, `SetSystemCursor`,
        `SystemParametersInfoW`) in `_prepare_win32_functions()`.
  - [x] **Broken prompt dialog** (`grab failed: another application has grab`,
        couldn't type, wouldn't close): tray menu callbacks run *inside* the
        native message-dispatch callback (on Windows, literally inside
        WndProc) — creating/running a Tk modal there conflicts with the
        outer message loop. Fixed by dispatching the dialog (and the
        auto-mode toggle and quit handler, for the same reason) to their own
        short-lived thread from `TrayApp`, instead of running inline in the
        menu callback.
  - [x] **"What does Mode auto even mean?"** — valid product question: the
        toggle previously gated capture/learning, wake-word listening, *and*
        the cursor together, which is confusing since capture never executes
        anything on its own (confirmation always gates that). Redesigned per
        the user's choice: `HeyPeer.start_capture()`/`stop_capture()` now run
        natively at app launch, independent of the tray toggle. "Mode auto"
        (renamed "Mode auto (écoute vocale)" in the menu) and the cursor
        indicator are now specifically about wake-word listening readiness.
        Regression-tested (`test_auto_mode_toggle_does_not_affect_capture`).
- [x] Round 3 of real-Windows bugs, fixed 2026-08-29:
  - [x] **`OSError: Unexpected color cursor for IDC_ARROW`**: the extraction
        code assumed every default arrow cursor is the classic monochrome
        AND/XOR-mask kind, and hard-failed otherwise. The user's actual
        Windows cursor scheme uses a real 32bpp color+alpha bitmap (common on
        current Windows themes) — `hbmColor` was non-NULL, which the code
        treated as an error instead of a case to handle. Added
        `_extract_color_arrow()`: reads the 32bpp BGRA bitmap directly via
        `GetDIBits` and recolors by brightness (bright pixels -> tint at
        their original alpha, dark pixels stay black), same idea as the
        monochrome AND/XOR split, just against real color+alpha data.
        `_extract_recolored_arrow()` now dispatches on `hbmColor` instead of
        raising. Not independently unit-tested (would need deep ctypes
        struct-pointer mocking for low payoff) — needs real-Windows
        verification, like the rest of the cursor code.
  - [x] **"Mode auto" now defaults to ON at launch** (per explicit user
        request: "un ON/OFF... sur ON lors du lancement"). `run_tray()` and
        `run_cli()` both call `peer.tray.set_auto_mode(True)` right after
        `start_capture()`; the tray menu item is unchanged (still a plain
        toggle) so it can still be turned off for that session.
## Backlog (2026-08-31) — curated from a Rhasspy/Wyoming comparison, plus two
## still-open reports from earlier this session. Checked off as each lands.

Rhasspy (github.com/rhasspy) was researched as "what does an established local
voice-assistant project do that we don't". Full ranked list and what was
explicitly rejected (MQTT/Hermes, the full Wyoming multi-process split, closed
grammar as the *primary* NLU, a bolt-on speaker verifier, its old multi-engine
TTS/STT zoo) lives in this session's conversation record, not repeated here -
only what's actually being built is.

### Doing this round

- [x] **A cold-start gap in the wake-word detector itself.** Distinct from
      round 25's "the first Hey Peer was answered several seconds late"
      (that was Whisper's *verifier* model still loading) - this is the
      *detector* itself, scoring against a window openWakeWord seeds with
      ten seconds of synthetic silence at construction
      (`AudioFeatures.feature_buffer = self._get_embeddings(np.zeros(160000))`
      in its own source), so for the first `CLIP_SECONDS` of real listening
      the classifier is looking at something it never saw in training - a
      mix of real audio and that seed, not a clean clip. `start()` now
      reads and discards `CLIP_SECONDS` of real audio (`_prime_feature_
      buffer`) before entering the scored loop: no detection can fire from
      that unreliable window, whatever it would have scored. Two tests
      cover the mechanism (priming reads exactly `PRIMING_CHUNKS`, never
      scores or calls back; `start()` genuinely calls it, not just defines
      it - this project has shipped the "wired up but never written" gap
      before). **Unverified against real hardware/voice** - the mechanism
      is provable on a toy classifier, "does the real miss stop happening"
      is not, the same as every wake-word change in this project.
- [x] **Formalize action registration.** Not a full table-driven rewrite of
      `_dispatch_intent` - at 9 actions, a static coverage test buys the same
      safety property with far less risk to well-tested, working dispatch
      logic. Two mechanical tests now parse `_dispatch_intent`'s own source
      by AST: every member of `ACTIONS` must appear as a compared string
      literal somewhere in it, and every compared literal must name a real
      member of `ACTIONS` - catching both a forgotten branch and a stale one
      the moment the mismatch exists, not when a human happens to say the
      sentence live.
      Writing the second test found a real one immediately: `"ask"` had a
      whole `elif` branch - a different fallback message, a different
      follow-up window - that could never run, because the earlier
      `if intent.action in SPOKEN_ACTIONS:` block already returns for "ask"
      before the elif chain is reached. Existing tests only ever exercised
      the reachable branch, so this had been silently dead since
      `SPOKEN_ACTIONS` was introduced. Removed.
      Also: round 31's prompt-contradiction guard hand-copied its list of
      "things Hey Peer can do" as English phrases, itself exactly the kind
      of duplicated list the backlog note above worried about. It's now
      driven by a new `ACTION_DESCRIPTIONS` dict in `intent.py`, keyed by
      `ACTIONS` - a future action missing an entry there fails right where
      the action is declared, not silently inside a test file nobody
      thought to update.
- [x] **A local fast path for the small, closed vocabulary of file commands**,
      tried before the LLM call and falling back to it on no match. Handles
      exactly three fixed sentence shapes - `heypeer/nemotron/fast_path.py` -
      built from the single most specific verb the prompt lists for each
      action ("supprime"/"efface", "renomme ... en", "deplace ... vers"),
      deliberately never the wider synonym lists ("mets", "place", "fous",
      "lance", ...) the prompt also accepts, because several of those are
      shared verbatim across *different* actions - only the model can tell
      "mets" (move) from "mets" (play) apart from the object.
      Does no filename matching of its own: `runner.resolve_existing_filename`
      already does that, and `move_single_file`/`rename_file`/`delete_file`
      already call it, so this only extracts the raw spoken name and checks
      it resolves *before* returning anything - a candidate that doesn't
      resolve is a decline, not a best guess, and the instruction reaches
      Nemotron exactly as if this module didn't exist.
      Found while writing the tests, not the code: the destination-folder
      capture is `.+?` up to end of string, so "vers Archives s'il te plait"
      captured the whole trailing clause as the folder name. There is no
      folder-listing equivalent of `resolve_existing_filename` to validate
      that against for a *new* folder, and inventing one (word limits, a
      stopword list) would be exactly the kind of "probably fine" guess this
      module refuses to make - so a move only fast-paths to a folder that
      already exists. Moving into a brand-new folder still reaches Nemotron
      correctly, which already handles it.
      Also found while wiring it in: this project's own tests construct a
      follow-up turn directly (`on_wake_word(audio, followup=True)`) without
      a preceding real turn to populate history first - a reasonable,
      deliberate shortcut, but it meant the planned "skip the fast path
      whenever history is non-empty" check alone would have silently let
      the fast path answer a test built to exercise Nemotron's follow-up
      handling instead. `followup` is now checked explicitly, not inferred
      from history alone.
      Verified against the live model on every sentence it would take over:
      identical answers except one cosmetic difference ("le fichier 4"
      resolves to `src_filename="4"` locally vs `"4.txt"` from the model,
      since Nemotron does its own resolution before answering) that does not
      change the final action - `delete_file` re-resolves either way.

### Queued, lower urgency (not started)

- [ ] VAD gate in front of the always-on wake detector (`wyoming-satellite`'s
      approach: only feed audio to the detector when a VAD says "this is
      speech"). Cuts CPU spent scoring silence/room noise and likely reduces
      false triggers from music or TV, but needs a new dependency (Silero
      VAD) and real measurement before it's worth the added moving part.
- [ ] A stage-boundary event/replay log (raw audio in -> wake decision,
      transcript -> verifier verdict, transcript -> LLM JSON), so wake-word
      and prompt regressions can be tested against captured real audio
      instead of a human speaking into the mic every time. Directly serves the
      same goal as this project's own rule of verifying prompt changes against
      the live endpoint rather than mocks - most useful once
      the fast path above exists and there is more than one thing worth
      replaying.
- [ ] Synthetic-data augmentation for the wake-word model (TTS-generate many
      phrasings of "Hey Peer" as extra negatives/positives). Complements the
      current real-voice fine-tune rather than replacing it, but it's a
      training-pipeline exercise the user runs themselves, not app code -
      noted, not scheduled.

### Needs your eyes, not just code

- [ ] **Blob "3D depth toward the viewer."** Already attempted once (sphere-
      normal shading + Blinn-Phong specular + Fresnel rim + AO, round 25) and
      still reported as reading 2D. I can't see the actual render from here
      (Linux sandbox) and "does this look three-dimensional" isn't something
      a pixel-measurement test can answer even where I can render - it needs
      your eyes. Candidate techniques to try next, cheapest first: a slow
      light-direction sweep (a static key light gives no parallax cue even
      on a correctly-shaded sphere), a sharper/higher-contrast specular
      highlight, and a highlight position that drifts slightly with voice
      energy rather than staying screen-fixed.

## Next session (2026-08-30) — planning only, nothing started yet

Requested by the user before signing off for the night on 2026-08-29:

- [x] **Real wake-word training** — done 2026-08-29. Downloaded 3 Piper
      voices (en_US-lessac/amy/ryan-medium) via `piper.download_voices`,
      generated 200 real "Hey Peer" positives and, after two rounds of
      finding this inadequate (see below), 288 negatives (a large phrase
      list + noise), augmented, and trained `data/wakeword/hey_peer.onnx`
      (committed — it's ~16 KB, everything else under `data/wakeword/`
      besides it is gitignored: voices are 240 MB+, samples are 38 MB+ of
      generated wavs, both regeneratable from committed scripts).
      Two real bugs found and fixed along the way by actually stress-testing
      the trained model with simulated streaming (not just static held-out
      accuracy, which looked fine at 96% and hid both problems):
      - `train.py` always left-aligned clips (word at t=0, padding after),
        so the classifier partly learned that specific alignment rather
        than the word's content — added `_load_clip_variants()`, which
        places each clip at a random offset within the window during
        training so the model sees the word at many positions, matching
        what a continuously sliding runtime buffer actually looks like.
      - A single French Piper voice used for *both* positive and negative
        synthesis caused severe leakage: 82% of that voice's negative
        phrases false-accepted (median score 0.98) regardless of content,
        vs 5-31% for the English voices — the model had partly learned
        "sounds like this specific voice" instead of "hey peer" specifically
        (plausibly because Piper phonemizes English text through a French
        voice's own phonemizer, producing an unusual rendering). Dropped
        that voice from training entirely rather than chase a fix tonight.
      - Final measured numbers (synthetic held-out streaming evaluation,
        200 positive / 288 negative clips, simulated sliding buffer): at the
        shipped default threshold (0.9), **100% recall, ~6.9% false-accept
        rate**; at 0.5 (openWakeWord's usual default) recall is the same but
        FAR rises to ~14%. **This is synthetic-voice-only evaluation — real
        human speech (especially the user's own voice/French accent) may
        behave better or worse; the live mic test is the real verdict.**
      - Added a temporary debug mode (`HEYPEER_WAKEWORD_DEBUG`, on by
        default): live dB meter + score per chunk and the input device name
        at startup, specifically so a "nothing happens" report can
        distinguish a silent/wrong mic from a wake-word accuracy problem.
      - Known limitation, not fixed tonight: only 3 English voices/accents
        in the training data — no French-accented "Hey Peer" positives.
        Real generalization to the user's actual accent is unverified.
      - Regenerating: `python -m heypeer.wakeword.generate_samples`, then
        `generate_negatives`, `augment`, `train` — see each script's
        docstring; voices need re-downloading via
        `piper.download_voices.download_voice`, not committed.

### Live wake-word test on real hardware (2026-08-29, later that night)

**"Hey Peer" was detected for real, on the user's actual voice, score 1.00,
repeatedly.** First real confirmation the whole trained pipeline works outside
synthetic evaluation. Getting there took four more real bugs, each only
visible once the previous one was fixed and exposed the next:
1. Console mojibake (`▒` characters) swallowing the actual diagnostic text —
   not just em dashes this time, accented characters too (`é`, `É`), in the
   user's MINGW64/Git Bash terminal specifically. Every console `print()`
   string project-wide is now plain ASCII; tray labels (rendered via Win32
   Unicode APIs, different risk profile) were left accented.
2. `onnxruntime.NoSuchFile` loading `melspectrogram.onnx` — see the real
   wake-word section above; fixed by `_ensure_openwakeword_models()`.
3. `run_cli()` exiting almost instantly once the listener actually
   succeeded — nothing kept the process alive on the success path (the
   `while True: input()` fallback loop was accidentally the only thing doing
   that, and it's skipped when the listener works). Fixed with
   `peer._wake_thread.join()` on success.
4. **CPU load switched to openWakeWord's incremental streaming API**
   (`AudioFeatures.__call__`/`get_features`) instead of calling
   `embed_clips()` on the entire ~1.5s rolling window every single 80ms
   chunk — the user flagged the always-on listener as noticeably heavy, and
   measured per-chunk cost dropped to ~1.1ms after the change (from
   reprocessing ~24000 samples worth of melspec+embeddings every chunk to
   reprocessing ~1280). This is the actual mechanism real always-listening
   engines (Hey Siri, Alexa, OK Google) rely on — process only what's new,
   keep a rolling feature buffer, never recompute the whole window.
5. **`input()` didn't actually wait for keyboard input once the wake-word
   listener worked** — the wake-word audio thread's `on_detected` callback
   was calling `on_wake_word()` (which blocks on `input()`) directly, inline,
   on that same background thread. Confirmed empirically: identical
   `input()` code worked fine when called from the *main* thread (the old
   race-condition fallback path), but returned immediately with an empty
   string when called from the audio thread — a real Windows-specific
   quirk, not something documented cleanly, but reproducible. Fixed by
   having `on_detected` only enqueue a signal onto a new
   `HeyPeer._detections` queue; the actual instruction handling now happens
   on a proper consumer loop (the main thread in `run_cli()`, a dedicated
   thread in `run_tray()`) that's safe to block in.
6. **Added `heypeer/tray/debug_window.py`** — a small always-on-top Tk
   window logging each interaction live (wake detected, instruction heard,
   intent, confirm, result) via `HeyPeer._log()`, so debugging doesn't
   require untangling console output interleaved with the wake-word debug
   dB meter's carriage-return-redrawn line. Runs its own Tk mainloop in a
   dedicated thread; other threads only ever push through a thread-safe
   queue it polls (Tkinter itself is not thread-safe). Verified working for
   real in this sandbox (unlike most of this project's GUI code, which
   could only be reasoned about, not run, here).
7. **`--cli` mode now also shows a real (detached) tray icon** via
   `pystray.Icon.run_detached()`, specifically so "Quitter" works as a stop
   button — the user didn't want Task Manager to be the only way to stop a
   console session. `_on_quit()` now also enqueues a `_SHUTDOWN` sentinel
   onto `_detections` so the tray's Quitter can unblock the console's
   consumer loop, not just Ctrl+C.

### Requested next: real voice command + a real UI

The user was explicit that wake-word detection alone doesn't make sense
without also being able to *speak* the instruction — right now
`_default_get_instruction()` still requires typing after "Hey Peer" fires.
Also asked for a proper UI, sketched out concretely this time (not just "a
real UI" — an actual interaction design):

- [x] **Voice command capture + interpretation** — done 2026-08-30. Records
      audio right after wake-word detection (`WakeWordListener._record_instruction`:
      simple energy-based end-pointing on the same open mic stream, stops
      after ~0.8s of trailing silence or an 8s safety cap) and routes it
      through Nemotron... except not the way originally planned:
      **`NemotronClient.interpret()`'s audio content part is rejected by the
      real Nebius endpoint** — tested directly (not read from docs): every
      shape tried (`input_audio`, `audio_url`, `audio`, both OpenAI and vLLM
      conventions) got an identical 422 the instant the message content list
      contains anything but `text`/`image_url`. No `/audio/transcriptions`
      endpoint either (404). There is no audio input support on this
      deployment today, whatever Nemotron 3 Nano Omni supports natively.
      Pivoted to local transcription: `heypeer/wakeword/stt.py` wraps
      `faster-whisper`'s "base" model (CPU, int8) — auto-detects language
      (verified working for English and French), transcribes a several-second
      clip in well under a second once loaded, model load (~8s) is warmed up
      in the background at auto-mode-on rather than paid on first use.
      `NemotronClient.interpret_text()` gained an optional `screenshot_path`
      (confirmed `[text, image_url]` content list *does* work against the
      real endpoint) so visual context isn't lost by dropping native audio.
      Verified end to end for real: synthetic "move the invoice file to the
      archive folder" clip -> transcribed correctly -> Nemotron resolved
      `action=move_file, src_filename=invoice_march.pdf, dest_folder=Archive`
      picking the right file out of a mixed watched-folder listing.
      `interpret()` itself is left in the codebase (commented on why it's
      unused) in case the Nebius deployment adds audio support later.
- [x] **Conversation window with an audio-reactive circle** — done
      2026-08-30. `heypeer/tray/debug_window.py` evolved from a plain
      scrolling log into a small always-on-top window: a Tk Canvas circle
      above the transcript, whose radius/color react to state and live mic
      level — grey/still when idle, gently "breathing" while listening,
      growing with the actual input level while recording an instruction,
      breathing again (different colors) while thinking/speaking. This is a
      deliberately simplified take on "voice mode"-style UIs — a Canvas
      oval with linear-interpolated smoothing, not a shader/glow blob;
      called out explicitly so nobody mistakes it for more than it is.
      `WakeWordListener.start()`/`_record_instruction()` gained an optional
      `on_level(level, recording)` callback (0-1 normalized, `recording`
      distinguishes "still scanning for the wake word" from "capturing the
      instruction") to drive it. Verified running for real in this sandbox
      (state/level transitions exercised without crashing) — the visual
      result (does it actually look decent trying to react smoothly) is
      unverified, no way to eyeball a Tk window from here.
      Still open, if the plain conversation window isn't enough: a true
      per-turn *popup* window that appears in a screen corner specifically
      on wake-word detection and closes after, rather than one persistent
      window — and reusing/replacing the "Demander à Hey Peer..." tkinter
      dialog (manual-trigger-only today) with this one (wake-word-triggered).
- [x] **Conversation window rebuilt on pywebview, replacing Tkinter** — done
      2026-08-29, per explicit user feedback that the Tkinter Canvas version
      "n'est pas viable pour un produit final" (not viable for a final
      product). `heypeer/tray/debug_window.py` now loads a real HTML/CSS/JS
      page (`heypeer/tray/webui/conversation.html`) through `pywebview` (the
      OS's own web view — WebView2 on Windows, no extra runtime to ship),
      which gets actual modern CSS for free: a glassmorphism card
      (`backdrop-filter: blur`), a pulsing orb whose color/breathing/size
      react to state and live mic level via a `--level` CSS custom
      property, and a scrolling transcript of message bubbles (right-aligned/
      tinted for what the user said). Same public API kept
      (`log`/`set_level`/`set_state`) so `main.py` didn't need to change.
      **Real finding while building this**: constructing the window on a
      background *thread* (the original plan, matching the old Tk approach)
      hung the **entire interpreter** in this project's Linux dev sandbox —
      `webview.create_window()` never returned, and no other thread made
      progress either, consistent with the native call blocking without
      releasing the GIL (most likely cause here: no GTK/WebKit backend
      installed in this sandbox). Whether this specific failure mode can
      also happen on Windows/WebView2 is unverified, but a hang that can
      freeze the whole app is a real regression risk regardless of cause —
      so the window now runs in its own **`multiprocessing.Process`**
      instead of a thread, driven by a `multiprocessing.Queue` of JS
      snippets to evaluate. `Process.start()` returns to the caller
      immediately no matter what the child ends up doing, so even if window
      creation hangs or fails on some machine, the rest of Hey Peer keeps
      running unaffected — verified: `DebugWindow()` now returns in ~10ms in
      this sandbox (previously: indefinite hang), with no zombie process
      left behind. Verified: full test suite (79 tests) passes with
      `webview`/`multiprocessing.Process` mocked. **Not verified**: what the
      page actually looks like rendered for real (no GTK/WebKit backend here
      to render it, and no Windows machine in this environment) — this is a
      bigger unverified gap than usual for this project's GUI code, since
      even a real (non-visual) construction couldn't be exercised here at
      all. Needs a real run on the user's Windows machine to confirm (a) the
      window appears, (b) the glassmorphism/orb look as intended, (c) the
      orb animates smoothly with voice level, (d) transcript bubbles render
      correctly.
- [x] **Spoken confirmation (TTS)** — done 2026-08-30, alongside (not instead
      of) the existing text confirm prompt. `heypeer/tray/tts.py` wraps Piper
      (already a dependency, chosen specifically for "léger" — local, fast on
      CPU, reasonably natural — over adding a second engine): Hey Peer speaks
      what it's about to do before `confirm()`'s text prompt, and speaks
      "Done"/"I stopped, something looked off" after. Auto-downloads a
      default voice if missing, same pattern as
      `_ensure_openwakeword_models()`. Voice load (~1-2s) is warmed up in the
      background alongside the Whisper STT preload, not paid on first use.
      Verified for real: synthesis itself (Piper producing correct-duration,
      correct-sample-rate wav audio) — **not** verified: actual playback
      through a speaker, since this sandbox has no audio output device.
      Confirmation text is in English (matching the existing `confirm()`
      prompt's language) regardless of the user's own French — a French
      Piper voice could be added later if that mismatch bothers in practice.
- [ ] **Tray icon stays minimal** per the user's explicit preference: just
      the ON/OFF toggle (green/gray light) it already is — the popup UI
      above is a separate window, not an expansion of the tray menu itself.

- [ ] **A real UI**, beyond the tray icon — see the corner-popup design above,
      which supersedes the vaguer version of this item from the previous
      planning round. Still open regardless of scope: (b) a proper
      confirmation dialog instead of the console `input()` prompt (the CLI
      confirm gate was always meant as an MVP stand-in — likely subsumed by
      the spoken-confirmation item above), (c) a settings/onboarding screen
      (watched dir, API key check, wake-word status) so the user isn't
      hand-editing `.env`.
- [ ] **Skill log / inspection** — right now skills only live in
      `data/skills/skills.json` with no way to list, inspect, rename, or
      delete them short of hand-editing the JSON. After a few days of
      testing this is already annoying (see 2026-08-29's "trop de skills
      appris" comment). At minimum: a way to list current skills (tray menu
      item or small window) and delete ones that shouldn't have been
      learned. Consider also: a run history (what executed, when, success/
      failure), not just the learned patterns themselves.
- [ ] **Broaden the range of executable actions** — today only two paths are
      real: file moves (robust, filesystem-based) and generic pyautogui
      click/keypress replay (coded in `SkillRunner`/`ActivityWatcher` since
      the start, but **never actually exercised on a real click/keyboard
      target** — only file-move skills have been rehearsed for real).
      Concretely: pick a second real-world scenario that needs actual mouse/
      keyboard automation (not just files) and run it end-to-end on real
      hardware, exercising the pyautogui replay path and the Nemotron
      `verify_screen` visual-check hook for the first time for real.

Additional ideas worth considering (not requested yet — raise with the user
before starting any of these):
- [ ] **Undo for a direct file move / skill run** — a misfire currently
      requires manually moving the file back; a lightweight "undo last
      action" (tray menu item, keeps the last N move operations) would be
      cheap given file moves already know src/dest.
- [ ] **Safety limits** — a max `n_repetitions` per confirmation, and/or a
      rate limit on how often auto-execution can fire, as a guard against a
      Nemotron misfire looping something destructive. Currently unlimited.
- [ ] **Windows startup integration** — run Hey Peer automatically at login
      (Startup folder shortcut or a small installer), now that it's meant to
      live as a background tray app.
- [ ] **Packaging** — a one-file Windows build (PyInstaller or similar) so
      the demo doesn't require `git clone` + `pip install` on stage/video.
- [ ] Submission polish
  - [x] README install/run instructions kept accurate as pieces land
  - [x] Ethics/privacy section accurate (updated for click-coord/key-name replay
        metadata and the plain-char-key refusal)
  - [ ] 3-min demo video (outside coding scope — manual follow-up)
  - [ ] Nebius/NVIDIA tool feedback write-up for submission (manual follow-up)
  - [ ] Hosted demo URL or test build (manual follow-up — needs a real machine
        with mic/display and a live Nebius API key)

### Latency/fluidity pass (2026-08-30, requested explicitly)

Reviewed everything in the wake-word/instruction pipeline that could plausibly
cause the "moins de fluidité" the user reported. Most of it was already fixed
earlier in this same session, each for its own reason, and together they're
most of what a "latency pass" would have found anyway:
- The debounce fix (rising-edge + cooldown) was arguably the biggest fluidity
  win here in disguise — before it, ONE utterance triggered 3 full redundant
  transcribe→Nemotron→confirm→TTS cycles back to back, which reads as
  "laggy/unresponsive" even though each individual cycle was reasonably fast.
- The streaming-scoring switch (full-window `embed_clips()` every chunk ->
  `get_features()` incremental) already cut per-chunk cost from reprocessing
  ~24000 samples to ~1280.
- The `input()`-on-the-wrong-thread fix removed what looked like a hang.

One genuinely new finding from this pass: the debug dB-meter `print(...,
flush=True)` ran on *every* 80ms chunk — real console I/O + a flush syscall
12.5 times/second, indefinitely, whenever `HEYPEER_WAKEWORD_DEBUG` is on
(which is the default). Throttled to every 3rd chunk (~240ms) — still reads
as live, cuts that I/O by two thirds. Can't measure the real-world impact of
this one from this sandbox (a different terminal than the user's Git Bash/
MinTTY, where slow-pty console writes are the plausible failure mode) — a
plausible, well-justified fix rather than a measured one.

What's left un-investigated: actual per-step wall-clock timing on the user's
own hardware (Whisper transcription + Nebius network round-trip + Piper
synthesis + playback, chained) — everything in this pass was reasoned about
or measured in this sandbox, not profiled on a real end-to-end turn on
Windows. If it still feels slow after all of the above, the next step is
timing each stage for real rather than guessing further.

### Voice confirmation, French-first TTS, and console-noise fix (2026-08-29)

Real-hardware testing surfaced three concrete complaints: couldn't confirm an
action *by voice* (only by typing into the console), the console felt noisy
("moins loud" - less heavy) while listening, and Hey Peer's spoken
confirmations should be French by default.

- [x] **Voice-based confirmation**. Previously `confirm()` was always a
      console `input()` y/N prompt, even after a real spoken wake-word
      activation with a mic already in use - awkward, and the actual
      complaint here. Added `heypeer/confirmation/voice.py`
      (`parse_confirmation(text)`, recognizing French - oui/non/vas-y/
      d'accord/annule/arrete - and English - yes/no/sure/cancel - tokens,
      returns `None` for an unclear reply) and
      `heypeer.wakeword.listener.record_voice_reply()` (a short, ~4s VAD
      recording tuned for a one-word reply rather than a full instruction).
      `HeyPeer._confirm()` picks voice vs. the console gate based on whether
      the current turn started from real mic audio
      (`_last_turn_was_voice`) - the tray's manual typed prompt has no mic
      context to react to, so it still falls back to typing y/N. An unclear
      or failed voice reply defaults to "no" (safer than assuming yes).
      `_record_instruction`'s VAD loop was refactored into a shared
      `_record_with_vad()` helper so the two recording paths (a full
      instruction vs. a short yes/no) don't duplicate the end-pointing logic.
      Unit-tested (parsing, dispatch-by-turn-type, error handling); the
      actual live-mic round trip is unverified here, same as the rest of
      this project's audio-hardware-dependent code.
- [x] **French-first spoken responses**. `heypeer/tray/tts.py`'s default
      Piper voice switched from `en_US-lessac-medium` to `fr_FR-siwis-medium`
      (auto-downloads on first use, same as before); every `_speak(...)`
      call in `main.py` rephrased in French ("Je vais faire : ... Tu
      confirmes ?", "C'est fait.", "Je me suis arrete..."), plus a new
      spoken "Je n'ai pas compris cette instruction." for the
      previously-silent unrecognized-intent case. The user's own spoken
      *input* still works in English too - Whisper auto-detects language
      regardless (see `heypeer/wakeword/stt.py`), and `parse_confirmation`
      accepts both languages for the yes/no reply itself. Console log text
      (`_log`) is untouched/still English+ASCII - this only changes what's
      actually spoken aloud.
- [x] **Console noise**: `HEYPEER_WAKEWORD_DEBUG` now defaults to **off**
      (was on) - the live per-chunk dB meter was interleaving with actual
      conversation output (wake-word/instruction/confirmation logs from a
      different thread), reported as making the console "moins fluide".
      Wake-word detection is now confirmed reliable on real hardware (0.93-
      1.00 scores across multiple real utterances), so the meter's original
      purpose - diagnosing "nothing happens, is the mic even working" - is
      no longer the common case. Set `HEYPEER_WAKEWORD_DEBUG=1` to bring it
      back if a mic issue needs diagnosing again.

### Siri-style orb redesign (2026-08-29)

Follow-up to the pywebview switch, per a concrete design ask: a circle at the
top-center of the screen with animated waves radiating outward while
listening, similar to Hey Siri/iOS's voice-mode indicator, staying light and
fluid, matching the light/dark OS theme automatically.

- [x] `heypeer/tray/webui/conversation.html`: added three `.wave-ring`
      elements layered behind the orb, each a plain circular border that
      scales up and fades out on a staggered ~2.6s loop (pure CSS
      `@keyframes`, no JS/canvas driving it) - paused via
      `animation-play-state` whenever state is "idle" so nothing animates
      (or costs CPU) while Hey Peer isn't actively listening/thinking/
      speaking. Added a `prefers-color-scheme: dark` block so the card
      switches to a dark translucent background with light text
      automatically, matching the OS theme rather than committing to one
      look.
- [x] `heypeer/tray/debug_window.py`: the window is now positioned at the
      **top-center** of the primary screen (`webview.screens[0]`, falling
      back to pywebview's own default placement if screen info isn't
      available on some backend) instead of wherever the OS defaults an
      unpositioned window to.
- [x] Kept the conversation transcript below the orb rather than dropping it
      for a bare orb-only popup - preserving the discussion history was an
      explicit earlier requirement and nothing since has asked to remove it,
      just to make the *orb itself* more Siri-like and reposition the window.
      Still unverified rendered for real, same caveat as the rest of the
      pywebview work in this sandbox (see above).

### Confirmation removed, mic-echo gating, minimal orb UI, extended file actions (2026-08-29)

Real-world use surfaced several friction points; all fixed/implemented in one
pass since they touched overlapping code (mainly `main.py`'s dispatch and the
conversation window).

- [x] **Confirmation removed entirely.** The explicit "wants to: X — confirm?"
      gate (spoken+recorded reply, or console y/N) is gone — the user reported
      it caused more problems than it solved (a misheard voice reply defaulted
      to "no" and silently blocked real actions). Every resolved intent now
      executes immediately, still narrated out loud first. Deleted
      `heypeer/confirmation/` entirely (`cli.py`'s console y/N gate,
      `voice.py`'s oui/non parser, `heypeer.wakeword.listener.record_voice_reply`
      — all now unused) rather than leave dead code around. The safety net
      that replaces the gate: every direct file action is checked to resolve
      inside the watched directory before touching the filesystem
      (`_ensure_within` — see below), and deletes go to the recycle bin/trash,
      not a permanent unlink.
- [x] **Mic-echo gating** (the "Hey Peer hears its own voice" bug, reported
      with a specific headset). `WakeWordListener` gained `mute()`/`unmute()`;
      `start()`'s loop drains the mic without scoring/triggering while muted.
      `HeyPeer._speak()` now mutes before calling Piper and unmutes in a
      `finally`, so Hey Peer's own TTS playback can't be scored as speech or
      false-trigger the wake word. This is mic *gating*, not true acoustic
      echo cancellation (nothing is cancelled during genuinely simultaneous
      playback+speech, which real AEC like Discord's WebRTC stack handles) —
      a full AEC integration was out of scope here, but gating fully covers
      the reported symptom since Hey Peer never needs to listen for the wake
      word while it's actively talking.
- [x] **Conversation window reduced to just the orb**, per explicit request:
      dropped the transcript/card entirely — the real conversation lives in
      the terminal log now (`HeyPeer._log` just prints; `DebugWindow.log()`
      is gone). Restyled as a small white circle with an Apple-style colored
      accent (blue/green/purple/pink depending on state, matching system
      colors rather than a single brand color) instead of the previous
      glassmorphism card + Siri-blue-only palette. Window shrunk to 200x170
      and pinned flush against the screen's top edge (`TOP_MARGIN = 0`) so
      the orb reads as "emerging from" it.
- [x] **Extended file actions**: Hey Peer can now move (already existed),
      **rename, create (file or folder), and delete** a single named
      file/folder directly — no learned skill needed, same as the existing
      move path. `Intent` gained `new_name`/`target_name` fields; Nemotron's
      system prompt (`heypeer/nemotron/client.py`) documents all four new
      action shapes; `heypeer/executor/runner.py` gained
      `rename_file`/`create_file`/`create_folder`/`delete_file`.
      **`delete_file` uses `send2trash`** (recycle bin/trash), not a
      permanent unlink — deliberate, since there's no confirmation step any
      more to catch a bad delete before it happens.
      **Real security fix found while doing this**: the *existing*
      `move_file` path built `dest_dir = watched_dir / intent.dest_folder`
      with no check that the result actually stayed under `watched_dir` — a
      `dest_folder` value like `"../../etc"` would have escaped it entirely
      (Nemotron's own output, not user-typed, but nothing stopped a
      hallucinated or adversarial value from reaching the filesystem this
      way). Added `_ensure_within(base, target, what)` — resolves the target
      path and checks `Path.is_relative_to`, raising `ExecutionAborted` if it
      would land outside `watched_dir` — and applied it to *every* direct
      file operation (move/rename/create/delete), not just the new ones.
      Verified with dedicated escape-attempt tests (`../outside` for each
      action) confirming they raise and never touch the filesystem.

### Engineering hardening pass (2026-08-30) — no new features, per explicit user request

Real logs from a full CLI session on Windows surfaced three concrete problems
before any further feature work: STT transcripts were often garbled or
outright hallucinated, the wake-word listener kept re-triggering on
background chatter/its own TTS while a previous turn was still being
processed, and the redesigned orb UI still showed "a square" around itself
instead of a borderless circle. All three fixed:

- [x] **Whole-turn muting, not just during TTS playback.** The real log
      showed multiple "Mot d'activation detecte" firing back-to-back while a
      previous instruction hadn't even finished being logged/transcribed yet
      — muting previously only wrapped the brief `_speak()` window, so the
      wake-word audio thread kept scoring (and could re-trigger on ambient
      chatter, or on Hey Peer's *own* narration) all through the
      transcribe -> interpret -> execute stretch of a turn, which is by far
      the longest part. Moved the mute to `_on_wake_detected` (fires the
      instant a detection comes in, before even enqueueing) and the unmute to
      a `finally` at the very end of `on_wake_word`/`_handle_instruction` —
      Hey Peer now fully finishes one turn before it can hear a new wake word
      at all, matching how real assistants (Alexa, Siri) turn-take rather
      than process overlapping requests. `_speak()` no longer touches the
      listener itself (redundant now that the whole turn is covered).
- [x] **STT accuracy**: real transcripts showed two distinct failure modes —
      garbled short words/filenames ("4.xt"/"4.tx" instead of "4.txt", "des
      places" instead of "déplace") and outright hallucinated sentences over
      background noise/silence with zero real speech in them ("Il est gigant
      d'habille, putain." — a textbook Whisper hallucination-on-silence
      artifact). `heypeer/wakeword/stt.py`: bumped the model from "base" to
      "small" and added a French-biased `initial_prompt` (targets the first
      problem — better baseline accuracy and vocabulary bias, without forcing
      a specific language so English instructions still work), and enabled
      `vad_filter=True` (faster-whisper's built-in Silero VAD, skips
      non-speech stretches instead of transcribing them — targets the second
      problem specifically). Not re-measured against a real held-out
      accuracy benchmark (would need a fresh batch of real recordings) — this
      is a well-targeted, reasoned fix based on the actual failure patterns
      observed, not a measured improvement number.
- [x] **"A square persists around" the circle** — the orb window's real
      on-screen appearance still wasn't a clean borderless circle. Two
      plausible causes addressed: (1) Windows' DWM draws a native drop
      shadow behind frameless windows by default, which reads as a
      rectangular halo around a small transparent shape inside it —
      pywebview's `create_window(..., shadow=False)` disables this, now
      passed. (2) if pywebview's backend auto-detection ever silently fell
      back to the legacy MSHTML/IE engine (which doesn't support
      `transparent` at all and paints an opaque rectangle — also consistent
      with "a square"), it would fail silently; `webview.start(...,
      gui="edgechromium")` now forces the modern WebView2 backend explicitly,
      so a real failure surfaces as a loud error instead of a silently
      degraded render. Still unverified for real (no GTK/WebKit backend in
      this sandbox to render anything with) — needs the user to confirm
      whether the square is actually gone now, or whether it's a third,
      still-unidentified cause.

### Round 2 of engineering hardening (2026-08-30) — real Windows CLI session

Another real CLI session on Windows surfaced two new concrete problems and
confirmed the previous transparency fix didn't fully work.

- [x] **Activation chime + orb only visible during an active turn.** The
      user reported being unsure whether Hey Peer actually heard "Hey Peer"
      at all (no audible or visual confirmation at the moment of
      detection), and — separately — that the always-visible orb
      (breathing quietly through "idle"/"listening") wasn't what they
      wanted; they asked for a Siri-like experience where a sound plays and
      the circle *appears* right when detected, rather than sitting on
      screen continuously.
      - `heypeer/wakeword/listener.py`: added `play_activation_chime()` — a
        short, synthesized two-tone rising chime (not a TTS phrase, much
        faster), played the instant `_maybe_trigger` fires, before
        `_record_instruction` even starts.
      - `heypeer/tray/debug_window.py`: the window now starts hidden
        (`hidden=True`) and `set_state()` calls `window.show()`/`.hide()`
        (a new show/hide/eval command protocol over the same queue,
        replacing the old raw-JS-string-or-None-sentinel one) — visible
        only for `recording`/`thinking`/`speaking`, hidden for
        `idle`/`listening`.
- [x] **"A square persists"/"a white rectangle" — still present after the
      first fix (`shadow=False` + `gui="edgechromium"`).** Rather than keep
      chasing pywebview's own `transparent` flag (which two rounds of
      real-hardware testing now show isn't reliably working for whatever
      pywebview version/backend combination is installed), switched to a
      technique this project doesn't depend on pywebview for at all: the
      page now renders on a solid "magic pink" (`#ff00ff`) background, and
      once the window has loaded, direct Win32 calls
      (`SetWindowLongW`/`SetLayeredWindowAttributes` with `LWA_COLORKEY`,
      via ctypes — same pattern and the same explicit-argtypes discipline
      as `heypeer/tray/cursor.py`) make every pixel of that exact color
      transparent/click-through. `transparent=True` is no longer passed to
      `create_window` to avoid pywebview applying its own (possibly
      conflicting) layered-window attributes first. Unverified for real
      still (no Windows machine in this sandbox) — but this no longer
      depends on the specific behavior this project has now seen fail
      twice.
- [x] **Folder name not preserved — real bug, not a guess.** "Déplace le
      dossier 6.txt dans le dossier test" resulted in a **new folder named
      "tests"** (plural) being created instead of "test" (singular, what
      the transcript actually said). Root cause: `_watched_files()` only
      ever listed *files*, never folders, so Nemotron had no way to know
      "test" already existed (or didn't) and invented a plausible-sounding
      variant instead. Added `HeyPeer._watched_folders()` and a
      `watched_folders` param on `NemotronClient.interpret_text()`, wired
      through every call site; the system prompt now explicitly instructs
      Nemotron to reuse an existing folder's exact name verbatim if one is
      given and matches, and otherwise use the name **exactly as the user
      said it** — never pluralize, translate, or rephrase it — for both
      `move_file`'s `dest_folder` and `create_folder`'s `target_name`.

Also still true and worth re-flagging alongside these: the "activation
happens even without saying Hey Peer" concern is a wake-word *model*
accuracy question (trained on synthetic Piper voices only — see the
"Real wake-word training" entry above), not something this pass touched;
the chime at least now makes a real trigger audible immediately, which
should make false positives easier to notice and report specifically.

### Round 3: two-stage wake-word verification + blob UI (2026-08-30)

Two problems from a real session, one of them the most important bug in the
project so far.

- [x] **The wake word triggered on basically any speech** — real logs show
      scores of 0.93-0.99 on sentences that never contained "Hey Peer".
      Root cause is the model itself, not a threshold: it was trained on
      synthetic Piper speech only (3 English voices, no real humans, no
      French accent — see the "Real wake-word training" entry above), so
      what it actually learned to separate is "synthetic-speech-like audio"
      vs "noise", not this phrase vs other phrases. No threshold fixes that,
      because the false-positive scores are *higher* than plenty of true
      positives. Retraining needs real recorded negatives (ideally the
      user's own voice), which aren't available here.
      Implemented the architecture real always-listening assistants use
      instead: a **two-stage cascade** — the cheap always-on detector only
      *proposes*, and a more accurate model *confirms*. Whisper already runs
      on the captured audio, so verification is free:
      - `WakeWordListener` now keeps a 2s rolling prebuffer and prepends it
        to the emitted audio, so the wake word itself (which is over by the
        time detection fires) is part of what gets transcribed.
      - `heypeer/wakeword/verify.py` (new): normalizes the transcript
        (lowercase, accent/punctuation-stripped) and scores a sliding window
        over its *opening* against "hey peer" with `difflib`. Fuzzy on
        purpose — Whisper renders it "Hey Pierre"/"Hey, Peer."/"hey pir"
        depending on accent, and enumerating spellings is exactly the
        brute-force approach rejected earlier for yes/no. Only the opening
        is searched, so a chance match late in a long sentence can't
        validate a false trigger.
      - `_interpret_audio` returns `None` for an unverified trigger (logged
        quietly, not spoken — announcing every false positive out loud would
        be worse than the false positive) and otherwise strips the wake word
        before sending the instruction on.
      **Verified against the exact transcripts from the user's real logs**:
      all 6 real false triggers rejected, all 4 real activations accepted
      with the instruction cleanly extracted. That's a real-data check, not
      just synthetic unit tests — but it is a check of the *verifier* on
      transcripts, not an end-to-end run on live audio, which still needs
      the user's hardware.
- [x] **Fixed a second real bug the same logs exposed**: "Hey, Peer. Déplace
      le fichier 4." was passed to Nemotron *including* the wake word and
      truncated, Nemotron answered `dest_folder="unknown"`, and Hey Peer
      created a folder literally named `unknown` and moved the file into it.
      Two fixes: the wake word is now stripped (above), and
      `_has_placeholder_name` treats "unknown"/"none"/"null"/... as
      "Nemotron couldn't determine this" rather than a literal name, asking
      the user to repeat instead of acting.
- [x] **UI reworked into an actual blob**, per reference designs: no
      rectangular window, a blue -> violet -> magenta gradient blob with an
      organic morphing silhouette (animated asymmetric `border-radius` —
      the reference article's own approach is React Three Fiber/WebGL, far
      too heavy for an always-running indicator, and CSS gets an
      indistinguishable result at this size), which **slides down from the
      top edge like a notification** on activation and slides back up after.
      Morph speed and palette shift per state; scale tracks the live mic
      level. Also switched the transparency color key from magenta to
      **black** — magenta sits inside this blob's own palette, so
      anti-aliased edge pixels blended toward it would have left a pink
      fringe; blending toward black reads as a natural soft shadow instead.
      `DebugWindow.set_state` now dedupes unchanged states, which matters
      because it's called ~12x/second from the audio callback and each
      show/hide drives a real window transition (one of which sleeps
      through its slide-out animation).

### Round 4: real transparency, supplied chime, adaptive end-pointing (2026-08-30)

- [x] **The black rectangle — root cause finally found, by reading
      pywebview's source instead of guessing again.** Two earlier attempts
      failed for reasons now recorded in `debug_window.py`'s module
      docstring; the important one is that attempt #2 (Win32 layered-window
      color key) *cannot* work here at all: WebView2 renders through
      DirectComposition into its own child surface, which the parent
      window's color-keying never sees. It's the right technique for a plain
      GDI window and the wrong one for a hardware-composited web view.
      pywebview 6.2.1 *does* implement transparency properly for
      EdgeChromium (sets the WebView2 controller's `DefaultBackgroundColor`
      to `Color.Transparent`, plus a Show/Hide dance to make it take
      effect) — but `platforms/winforms.py` gates it behind an `if/elif`:

          if window.hidden:                      # <- our case
              ...
          elif window.transparent and is_chromium:
              browser.Show(); browser.Hide()     # the hack that makes it work

      Passing `hidden=True` (added in round 2, so the blob would only appear
      during a turn) therefore silently disabled the very transparency setup
      needed. Now created with `transparent=True` and *not* hidden, then
      hidden from the command pump a moment later. Real per-pixel alpha also
      made it worth adding back the level-reactive glow that color-keying
      couldn't have rendered without a halo.
- [x] **Activation chime now uses the mp3 the user supplied**, converted
      once to a trimmed mono 16 kHz WAV (`heypeer/assets/`, see the README
      there for provenance and the regeneration snippet) rather than decoded
      at runtime — libsndfile only reads mp3 from 1.1 onward, which isn't
      guaranteed on every install. **Also fixed a real problem introduced
      with the chime in round 2**: it was played synchronously, so
      instruction recording didn't start until it finished — dropping the
      first ~0.66s of speech for anyone running the wake word straight into
      the instruction ("Hey Peer, déplace le fichier..."), which is exactly
      how the user speaks in every real log. Now played on its own thread.
- [x] **End-pointing reads the actual decibel spectrum instead of a fixed
      cutoff**, per the user's request to "regarder le spectre de décibel
      pour comprendre lorsque je parle et lorsque je ne parle plus". Real
      instructions were being truncated mid-sentence ("déplace le fichier
      4.0.", "Déplace le fichier 4.txt-"). Three changes in
      `_record_instruction`:
      - The speech/silence cutoff is now derived from the room's measured
        noise floor (`estimate_noise_floor` — the 20th percentile of
        per-chunk levels over the prebuffer, a low percentile rather than a
        mean so speech in the window can't drag it up) plus a 12 dB margin,
        clamped to a sane range. Measured effect: a very quiet room gets a
        -54 dBFS threshold and a noisy one -25 dBFS, where before both got a
        fixed -40 dBFS — too high to hear a quiet speaker, too low to ignore
        a fan.
      - Trailing silence needed to end a recording went from ~0.8s to ~1.2s;
        people pause naturally between a filename and a destination, and
        that pause was being read as "done".
      - A minimum recording duration, so a slow start can't truncate an
        instruction to nothing.

Still open and unchanged: the wake-word *model* remains
synthetic-voice-trained, so the always-on detector still over-fires — the
round-3 second-stage verifier is what makes that survivable, not a fix to
the model itself. Retraining with real recorded negatives is still the real
fix and still needs audio that doesn't exist yet.

### Round 5: stop capturing input habits, react only after verification (2026-08-30)

- [x] **Input capture off by default — and the reason it was slow, fixed.**
      The user reported the machine noticeably slowing down with capture on.
      Root cause found: `ActivityWatcher._poll_active_window()` ran on
      *every* keypress, click and scroll, and `get_active_window()` goes
      through Win32 plus a process lookup — so typing in an IDE meant one
      system query per character. Throttled it to at most once every 0.5s
      (focus changes are a human-scale event; nothing pattern detection
      needs is lost). Separately, and as asked, global mouse/keyboard
      capture is now **off by default** (`HEYPEER_CAPTURE_INPUT=1` to
      re-enable) since the skills it learned from IDE/terminal noise were
      mostly junk anyway. File-move capture — cheap, and what the demo skill
      actually learns from — stays on.
- [x] **The chime and the blob no longer fire on unverified triggers.** This
      was the substantive bug behind "il s'active même lorsque je ne le dis
      pas" and "détecté alors que je ne l'ai pas dit, ou trop rapide entre
      le hey et le peer". Round 3 added transcript verification, but it ran
      *after* the whole turn, while the chime and the indicator still fired
      on the raw detector trigger — so every false positive was still fully
      visible and audible, just harmless afterwards.
      Verification now happens on the prebuffer (which already contains the
      wake word) and gates all of it: `WakeWordListener.start` takes an
      `on_verify` callback, and `HeyPeer._verify_wake_word` transcribes,
      checks, and only *then* plays the chime and shows the blob.
      Verification runs on its own thread **concurrently with recording**
      rather than before it — doing it first was simpler but would have left
      a few hundred ms hole in the captured audio for anyone running the
      wake word straight into the instruction, which is how the user
      actually speaks in every log. A rejection aborts the in-progress
      recording early. A *failing* verifier (missing model, transcription
      error) is treated as acceptance, so a bug there can't make Hey Peer
      deaf. `_on_audio_level` no longer sets the window state either — it
      would have popped the blob up during the pre-verification recording.
- [x] **The rectangle around the blob — fourth attempt, and this one doesn't
      depend on the renderer.** Attempt 3 (pywebview `transparent=True`) got
      WebView2 itself transparent, but a grey rectangle remained: reading
      `platforms/winforms.py` again shows that branch sets the *WebView2*
      background transparent and never the WinForms `Form` behind it, which
      keeps its default Control-grey — the see-through web view was just
      revealing the grey form. Now the window is additionally clipped with
      `SetWindowRgn` to an inscribed ellipse. A window region is applied by
      the window manager itself, so pixels outside it are not part of the
      window regardless of what renders inside — independent of compositors,
      alpha support and background colors, which is the exact class of
      assumption the first three attempts each died on.
      Deliberate trade-off, worth stating plainly: the silhouette is now the
      region's circle rather than the reference design's irregular morphing
      outline. The page paints the blob edge-to-edge so every pixel inside
      the circle is blob (no grey gap), and the organic quality comes from a
      drifting gradient and level-driven brightness *inside* the circle
      instead of from the outline. A rectangle-free circle that reacts beats
      an irregular blob sitting in a grey box.

### Round 6: the animated blob, genuinely borderless (2026-08-30)

Round 5 removed the rectangle by clipping the window to a fixed ellipse,
which worked but looked — accurately — truncated, and lost the organic
outline of the reference design. The answer to "n'est-il pas possible de
créer un cercle sans bordure ?" is yes, and the fixed ellipse was an
unnecessary concession: `SetWindowRgn` takes an **arbitrary polygon**, not
just an ellipse, and it can be replaced every frame.

- [x] **`heypeer/tray/blob_shape.py`** (new): the outline as a pure function
      of (time, level) — a radius modulated by three low-frequency harmonics,
      `r(θ,t) = R·(1 + Σ aᵢ·sin(kᵢθ + ωᵢt + φᵢ))`. No drawing, no Win32, so
      it is fully unit-testable without a display, which nothing about the
      previous CSS-animated silhouette was. Tests cover the properties that
      actually matter: it never escapes the window (anything outside gets
      clipped, which is exactly what made the ellipse version look cut off),
      it's measurably irregular rather than a disc, neighbouring points stay
      close enough to show no facets, it changes over time, and it grows
      with the mic level. Also rasterized it to ASCII during development to
      look at the silhouette rather than only asserting on numbers.
- [x] **The region is now the single source of the shape.** The page paints
      a full-bleed gradient and defines no outline at all; the window region,
      rebuilt every frame from `blob_points`, carves the silhouette out of
      it. This inversion is the substantive fix: any design where CSS
      animates a shape *and* a region clips it has two independent notions of
      the outline that inevitably disagree — whatever the region doesn't
      cover is chopped off, whatever the page doesn't paint shows as grey.
      With one source there's nothing to keep in sync, and no per-frame
      JavaScript either (only a local `CreatePolygonRgn`), so the whole
      animation costs one cheap Win32 call per frame.
- [x] **Real size reaction to the voice is back**: `blob_points` takes the
      level, so the silhouette itself swells when the user speaks. The
      fixed-ellipse version could only fake that with brightness.
- [x] **The slide-in now moves the window** rather than CSS-translating its
      contents — with the region locked to the window's own coordinates, a
      CSS translate would have slid the gradient out from under the region.
      Eased exponentially toward a target so an interrupted slide retargets
      instead of jumping.
- [x] Animation idles at 10 Hz doing nothing while off screen (the common
      case) instead of running the frame loop continuously — worth being
      careful about given the performance problems reported in round 5.

### Round 7: drop the web view, render the indicator ourselves (2026-08-30)

- [x] **Crash on an empty model answer.** `message.content` is None when
      Nemotron returns no usable completion, surfacing as "the JSON object
      must be str, bytes or bytearray, not NoneType" — useless to the user.
      An empty *or* non-JSON answer now resolves to an unknown intent;
      `verify_screen` got the same treatment.
- [x] **Action latency**, two real causes, both fixed: the narration was
      spoken **synchronously before acting**, so the file didn't move until a
      whole sentence had played; and the screenshot was a full-resolution
      PNG, measured at ~730 KB base64 versus ~31 KB for a 768px JPEG with
      the same context (23x). Narration is now fire-and-forget, the
      screenshot downscaled.
- [x] **Dropped the trailing "C'est fait."** — announcing the action already
      tells the user it happened. Failures still speak, since that's the one
      case where the narration would otherwise be a lie.
- [x] **The indicator no longer uses a web view at all.** Rounds 2-6 each
      failed to get a borderless, good-looking overlay out of
      pywebview/WebView2 — color-keying can't see a DirectComposition
      surface; `transparent=True` leaves the WinForms form's grey behind it;
      `SetWindowRgn` works but is a **1-bit mask**, so edges are hard and
      aliased and a glow is impossible by construction. Every attempt was
      trying to talk a browser engine into something Win32 exposes directly.
      `UpdateLayeredWindow` composites a 32-bit BGRA bitmap into the desktop
      with genuine per-pixel alpha. So:
      - `heypeer/tray/blob_render.py` (new) draws the frame with PIL/numpy:
        organic silhouette supersampled 3x for antialiasing, diagonal
        gradient, and a real glow (the silhouette blurred well past its own
        edge, so it follows the shape as it morphs).
      - `heypeer/tray/overlay.py` (new) is the Win32 layered window —
        click-through, never steals focus, never in the taskbar.
      - `debug_window.py` is now just orchestration; the HTML page and the
        `pywebview` dependency are gone.
      **The look is finally testable.** 12 new tests assert what kept
      regressing where only the user could see it: corners fully
      transparent (no background), centre fully opaque, a substantial band
      of *partial* alpha (i.e. antialiased, which a 1-bit region cannot
      produce), the glow reaching past the solid silhouette, growth with mic
      level, and nothing clipped at the frame border. Also rasterized the
      alpha channel to ASCII to actually look at it.
      **Cost, measured**: `render_alpha` is the expensive half (~18ms) but
      depends only on time and level, never colour — so a 48-frame loop is
      pre-rendered once (~0.2s) and only the cheap `compose` runs per frame
      (~1.2ms, ≈3.6% of one core at 30fps), and only while on screen. Given
      the performance complaints in round 5, that mattered.

### Round 8: voice-to-action only, screenshot dropped, blob reacts to speech (2026-08-30)

- [x] **400 on every request — the screenshot.** The endpoint now rejects
      any non-string message content outright:
      `{'loc': ['body','messages',1,'content','str'], 'msg': 'Input should
      be a valid string'}` — the same shape of refusal that killed audio
      input earlier. A `[text, image_url]` list did work here before, so
      this is a deployment change, not a mistake in the request. Stopped
      sending it. For the file actions Hey Peer performs, nothing is lost:
      the grounding that matters is the real file/folder listing, not a
      picture of the screen — and skipping the capture, resize and upload is
      faster too. `interpret_text` still accepts `screenshot_path` and still
      builds the multimodal content list, documented as currently unusable,
      in case the deployment regains support.
- [x] **Skill learning off; voice-to-action only** (`HEYPEER_LEARN_SKILLS=1`
      to re-enable). Every learned skill was being sent to Nemotron on every
      request — the 400's payload shows a dozen entries all named "Repeated
      sequence in unknown app" — bloating the prompt with things that could
      never match a spoken instruction. With it off, the prompt for a real
      instruction is **135 characters**. Skills already on disk aren't even
      loaded now, so a backlog can't leak back in; deleting
      `data/skills/skills.json` removes them for good.
- [x] **The blob now reacts to *how* the user speaks, not just that they
      do.** Level previously only scaled it, which reads as a balloon
      inflating. It now also deepens the wobble (~1.9x) and speeds the
      morph up (~2.2x), so loud speech visibly agitates the shape —
      measured: radius spread goes 12.5px -> 23.0px from silence to full
      level, on top of the size change. Since the outline itself now depends
      on level, one pre-rendered loop can no longer be scaled to fake it, so
      frames are pre-rendered per level bucket (5 x 40 = 1.1s once, in the
      background process, ~11 MB). The raw level is smoothed before picking
      a bucket, or the shape would snap on every syllable.
- [x] Added a specular highlight to the gradient — a flat diagonal ramp read
      as a sticker; lifting the upper left toward white makes it read as a
      lit volume, matching the reference design.

Still open: the user reports slow startup. Removing the skill load helps a
little, but the dominant cost is almost certainly loading the Whisper
("small") and Piper models, which happens on background threads and is
inherent to running them locally. Worth profiling for real before changing
anything — a smaller Whisper model would trade back the transcription
accuracy that fixed the garbled-filename problem.

### Round 9: filename resolution, easier wake word, 3D blob, faster start, better voice (2026-08-30)

- [x] **"renomme le fichier 4 en 15" was answered as unrecognized.** People
      say filenames the way they say them — without the extension, sometimes
      mistranscribed ("15.xt"). Expecting the model to reconstruct the exact
      string was the wrong place to solve it. Added
      `resolve_existing_filename`, which matches what was said against the
      folder's real listing in order of decreasing confidence: exact →
      case-insensitive → stem ("4" → "4.txt") → unique prefix ("facture" →
      "facture_mars.pdf") → fuzzy ("15.xt" → "15.txt"). It **declines rather
      than guesses** when two files would match (4.txt and 4.pdf), because a
      wrong file is worse than asking again. Wired into move/rename/delete;
      renames also inherit the source extension when the new name has none,
      so "en 15" gives 15.txt rather than an extension-less file. The prompt
      now also states that instructions are spoken and transcribed.
- [x] **Wake word detects more easily**: threshold 0.9 → 0.55. It used to be
      the only thing between a detection and an action, so it had to be
      strict, at the cost of missing real activations. Now that the
      second-stage verifier gates everything, being permissive at stage one
      is nearly free — extra false positives die silently a moment later,
      while genuine "Hey Peer"s scoring 0.6-0.85 get through instead of
      being dropped. Permissive stage one, strict stage two is the point of
      a cascade.
- [x] **The blob is properly 3D.** The flat diagonal ramp read as a sticker.
      It's now shaded as a lit sphere: a surface normal is reconstructed
      from the distance to the centre (`z = sqrt(1 - x² - y²)`) and lit with
      a Lambert term, a tight specular lobe, and a rim light so the
      silhouette reads as curved. Measured brightness spread across the
      blob: 82 levels (was flat). Since the shading only depends on size and
      palette, `_gradient` is now cached — per-frame cost actually *dropped*
      from 0.75ms to **0.16ms** despite the much heavier maths.
- [x] **Faster startup.** Profiled rather than guessed: the two real costs
      on the startup path were `pywinctl` (pulls pywin32 + comtypes on
      Windows, one of the slowest imports in the app) — imported for input
      capture, which is off by default — and building the OpenAI client.
      `pywinctl` is now imported lazily inside `get_active_window`, and the
      OpenAI client is constructed on first use. Confirmed `pywinctl` is no
      longer in `sys.modules` after importing `heypeer.main`.
- [x] **More human voice.** Checked the published voice list: Piper has **no
      "high" quality French voice** — `medium` is the local ceiling. Within
      that, switched the default from `fr_FR-siwis-medium` to
      `fr_FR-upmc-medium` and moved the synthesis parameters off Piper's
      flat defaults (slightly slower, more prosodic variation via
      `noise_w_scale`, which is most of what "robotic" means). **This could
      not be verified by ear here**, so rather than baking in a guess both
      the voice and speaker are overridable — `HEYPEER_TTS_VOICE`,
      `HEYPEER_TTS_SPEAKER` (upmc ships jessica=0, pierre=1) — with the
      alternatives listed in the module docstring.
- [x] **Fixed a test that was silently hitting the network**, downloading a
      75 MB voice on every run: it stubbed `sys.modules["piper.download_voices"]`,
      but `from piper import download_voices` takes the attribute off the
      already-imported package and never consults `sys.modules`, so the stub
      was ignored. Now patches the function on the module itself.

### Round 10: chaining, detection latency, UI smoothness, voice pace (2026-08-30)

- [x] **"Je ne peux pas enchaîner avec un autre Hey Peer" — a real bug, not
      a feel.** While muted for a turn, the loop skipped `process_chunk`
      entirely, so openWakeWord's streaming feature buffer still held the
      wake word that had just fired. On unmute it kept scoring high, and
      since `_maybe_trigger` only re-arms once the score drops *below*
      threshold, the listener stayed deaf until ~1.5s of fresh audio flushed
      it. Fixed by feeding silence during mute (keeps the buffer moving,
      can't score high) and re-arming explicitly in `unmute()`. Two
      regression tests cover both halves.
- [x] **"Je dois me répéter" — the verifier was the new bottleneck**, not
      the detector (whose threshold had just been *lowered*). Two causes:
      the ~2s verification clip was transcribed with `vad_filter=True`,
      which frequently discards a clip that short and returned nothing; and
      an empty transcript was treated as a rejection. Now verification runs
      without VAD, and an empty transcript **defers** to the full-audio
      check rather than rejecting — uncertainty is not a refusal.
- [x] **Chime latency**: verification runs before the chime, so its cost is
      felt directly. Measured on a 2s clip: 0.99s with "small" vs **0.37s
      with "base"**. Verification only has to recognise one fixed short
      phrase (matched fuzzily afterwards), so it now uses `base` while the
      instruction keeps `small`, where accuracy decides whether a filename
      comes out as "4.txt" or "4.xt". Right-sized model per job.
- [x] **UI smoothness — found the real cost.** `Overlay.update` created *and
      destroyed* a screen DC, a memory DC and a DIB section on **every
      frame**, 30 times a second, plus re-declaring every ctypes signature.
      GDI objects are a finite per-process resource and allocating them is
      not cheap; that churn is what made the indicator feel heavy on a
      machine that should not struggle. The surface depends only on the
      window size, which never changes, so it is created once and reused
      (`_ensure_surface`/`_release_surface`).
- [x] **Voice pace**: `length_scale` had been set to 1.06 on the theory that
      slower reads as more natural; the user reported it simply as slow.
      Back to 0.95 (slightly brisker than default) — these are short
      confirmations, not narration. Also trimming Piper's leading and
      trailing silence before playback (~0.12s per utterance), which is
      heard as Hey Peer being quicker to start *and* to finish.

Proposed next, not yet built (all within the voice-to-action use case):
- **Follow-up window**: stay open for a few seconds after an action so a
  second command needs no wake word at all. The chaining bug above is fixed,
  but not needing to repeat the wake word would be better still. Needs care:
  it bypasses the verifier, so it should be narrow and clearly indicated.
- **"Annule"**: undo the last file action. Cheap — every operation already
  knows its source and destination — and the natural safety net now that
  there is no confirmation step.
- **Ask instead of failing silently**: when an instruction resolves to
  nothing, say what was missing ("quel dossier ?") rather than "je n'ai pas
  compris", so the user knows what to add.
- **Retrain the wake word on the user's own voice.** The detector is still
  trained on synthetic Piper speech only; it is the root cause behind both
  the false positives and the misses, and the cascade is a workaround for
  it. Recording ~50 real samples would fix the cause rather than compensate.

### Round 11: follow-up window, undo, and asking instead of failing (2026-08-30)

The three items proposed at the end of round 10, built.

- [x] **Follow-up window** — after Hey Peer acts (or asks a question), speech
      alone starts the next turn for ~6s, with no wake word at all. That is
      how a conversation actually continues, and it sidesteps the wake-word
      model entirely for the second command.
      `WakeWordListener.arm_followup()` opens the window; the loop checks it
      *before* wake-word scoring, since there is nothing to score against.
      A follow-up turn deliberately **skips verification** — there is no wake
      word in that audio by construction, so `on_verify` would reject every
      one — and `on_detected(audio, followup)` carries that fact through so
      `_interpret_audio` doesn't look for one either.
      The risk is real and bounded on purpose: for those few seconds, room
      speech can open a turn. It is kept short, requires speech well above
      the measured noise floor (a stricter margin than ordinary
      end-pointing), and the instruction still has to resolve to a concrete
      file action — ordinary conversation resolves to "unknown" and does
      nothing.
- [x] **"Annule"** — undo for the last file action, in
      `heypeer/executor/undo.py`. Each action records how to reverse itself
      *at the moment it succeeds*, because that is the only point where the
      resolved filename, the created folder and the extension inherited
      during a rename are all known; reconstructing them afterwards from the
      intent would be guesswork.
      Two deliberate refusals rather than blind reversal: undoing a file
      creation only removes the file if it is **still empty** (the user may
      have typed into it since), and undoing a folder creation only removes
      it if it is **still empty** (never take files with it).
      Deletes are the honest exception — `send2trash` offers no programmatic
      restore, so they are recorded as *not* undoable and Hey Peer says the
      file is in the recycle bin instead of pretending. That is still better
      than a permanent unlink, which is why deletes work that way.
- [x] **Ask instead of failing silently** — a new `ask` intent carrying a
      short French `question`. When the instruction is recognisable but
      incomplete ("déplace facture" with no destination) or genuinely
      ambiguous (two files match), Hey Peer says *what is missing* — "Vers
      quel dossier ?" — instead of a flat "je n'ai pas compris" that leaves
      the user guessing what to rephrase. It arms the follow-up window too,
      so the answer needs no wake word.

Next: retraining the wake word on the user's own voice — the root cause
behind both the false positives and the misses, which everything above only
works around.

### Round 12: personalising the wake word on the user's own voice (2026-08-30)

The root cause behind both failure modes, finally addressed rather than
worked around. The shipped model was trained on synthetic Piper speech only —
three English voices, no real humans, no French accent — so what it actually
learned to separate is "speech-like audio" from "noise", not this phrase from
other phrases. That is why it fired on ordinary speech *and* missed genuine
activations, and why the verifier, the permissive threshold and the follow-up
window all exist.

- [x] **`heypeer/wakeword/record_samples.py`** — guided recorder. Two sets,
      and the second matters as much as the first:
      - positives: the user saying "Hey Peer";
      - negatives: **the same voice** saying other things — near-misses
        ("Hey Pierre", "Hey Peter", "peur", "père", "Hey" alone), the real
        commands they give ("déplace le fichier facture vers Archives"), and
        ordinary speech.
      Recording only positives would be the classic mistake: the model could
      then separate the classes on voice identity alone (real human vs
      synthetic) and would fire on anything the user says. Same-voice
      negatives force discrimination on *content*. The command phrases target
      a specific observed failure — the detector firing partway through an
      instruction, just after the real wake word.
      Silent takes are rejected and the prompt retried, since a silent clip
      banked as a positive teaches that silence is the wake word.
- [x] **`train.py` takes multiple directories per class** (`--positive-dir`
      repeatable) so the user's recordings train alongside the synthetic set
      rather than replacing it. Directories whose name contains "user" get
      **more alignment variants** (16 vs 4): ~40 real takes against a few
      hundred synthetic clips would otherwise barely move the decision
      boundary, and oversampling through extra random alignments adds real
      variation instead of duplicating identical rows.
- [x] **`heypeer/wakeword/evaluate.py`** — streaming evaluation, because
      held-out clip accuracy has already deceived this project once: an
      earlier model scored 96% while being broken in two distinct ways that
      only streaming exposed. It feeds each clip through `AudioFeatures`
      chunk by chunk exactly as the listener does and takes the **peak**
      score, which is what the live listener actually reacts to, then reports
      recall and false-accept rate across candidate thresholds. It also says
      plainly whether the two distributions separate at all — if the worst
      positive scores below the best negative, no threshold works and the
      answer is more data, not a different number.
      Verified end to end here on a synthetic stand-in dataset: multi-dir
      training with user weighting, ONNX export, then evaluation correctly
      reporting clean separation and the usable threshold range.

The user's recordings stay local — `data/wakeword/samples/` is gitignored,
so a personalised model never puts someone's voice in the repository.

Usability fix after the first real attempt: passing four long paths by hand
failed immediately, and in a way that was easy to misdiagnose — on Git Bash
`data\wakeword\...` loses its backslashes (escape characters there), so the
error read "No wav files found in datawakewordsamplespositive_user" and
looked like missing recordings rather than a mangled path. Both `train` and
`evaluate` now default to the conventional sample directories, using
whichever exist, so the whole retraining flow needs no path arguments at
all; and a missing directory is now reported as such, separately from an
empty one, with a hint about separators.

Once the user has recorded and retrained, the threshold should be re-chosen
from `evaluate`'s table rather than kept at today's deliberately permissive
0.55, and the cascade's second stage can likely be relaxed too.

### Round 13: two real training bugs, found by the user's first personalised model (2026-08-30)

The first model trained on the user's own 40 positives and 26 negatives came
out **degenerate**: positives *and* negatives both scored 1.00 at every
threshold. Reproduced here from a synthetic stand-in built to match the shape
of his data, which then confirmed each fix.

- [x] **The model had learned "silence = Hey Peer".** Confirmed directly: it
      scored **1.0 on pure silence**. Cause: his negative set is all speech
      (near-misses, commands, ordinary sentences) because
      `negative_noise` — the synthetic noise directory — doesn't exist on his
      machine. His positives, meanwhile, are full of silence: 2s takes with a
      short word inside, plus alignment padding. Nothing ever told the model
      that quiet is *not* the wake word, and a live listener spends nearly
      all its time looking at exactly that, so every clip peaked at 1.00
      somewhere.
      Fix: `_silence_and_noise_clips` generates silence and faint broadband
      noise into the negative class on **every** run. This is categorical,
      not a nicety — a wake-word model must reject silence — so it can't be
      left depending on whether an optional generation script was ever run.
      Silence went from 1.0 to 0.01.
- [x] **Negatives were only ever seen fully voiced, so every speech onset
      scored high.** A positive is "silence, short word, silence" — which is
      exactly the shape of the *start* of any sentence. Negatives longer than
      the training window were reduced to their loudest, fully-voiced
      stretch, so the model never saw an onset labelled "not the wake word".
      Fix: `_sliding_windows` samples negative windows across the whole
      recording and deliberately lets them hang off either end, so onsets and
      offsets are represented — which is also precisely what the live
      listener sees as someone starts talking. Negatives went from max 1.00 /
      median 1.00 to max 0.98 / median 0.93, and the classes became
      separable.
- [x] **Positives were being truncated to their first 1.5s**, which after a
      countdown can be mostly silence — cutting the wake word out of its own
      training clip. `_loudest_window` keeps the highest-energy slice
      instead.
- [x] **`evaluate` now says its numbers are optimistic.** It scores the same
      clips the model trained on, and a model always fits what it was shown.
      It is a check that nothing is structurally broken (everything at 1.00,
      or negatives above positives) rather than a measure of accuracy — worth
      stating outright, since the whole reason this evaluation exists is that
      a 96% held-out score once hid two real bugs.

Honest limits: the reproduction used tones as a stand-in for speech, which
are harder to separate than real words, so the post-fix margin measured here
(0.98 vs 1.00) is pessimistic in one way and optimistic in another — the same
clips were used for training. The real verdict is the user retraining on his
own recordings and running the app.

### Round 14: the personalised model works — threshold raised, diagnostics named (2026-08-30)

Retraining on the user's own recordings with the round-13 fixes produced a
model that genuinely discriminates, where the previous one answered 1.00 to
everything:

    positives: min 0.10  median 1.00
    negatives: max 0.97  median 0.17
    at 0.95 -> 98% recall, 4% false accepts

Reading it: recall is flat at 98% across every threshold, so exactly one
positive take is unrecoverable (it scores 0.10 — almost certainly a bad
recording), and one negative reaches 0.97 while the rest sit near 0.17.

- [x] **Threshold back to 0.9** (from 0.55). The loose threshold was a
      workaround for a model whose false positives outscored many true ones —
      the only workable arrangement was a permissive first stage and a strict
      verifier. Now that the classes separate, the threshold can do real work
      again. 0.9 rather than 0.95 because these numbers are optimistic (the
      model was scored on the clips it trained on) and the two failure modes
      are not symmetric: a miss costs a repeat, while a false trigger is
      caught by the verifier moments later.
- [x] **`evaluate` names the problem clips** instead of advising "record more
      samples", which nobody can act on. It lists the lowest-scoring
      positives and the highest-scoring negatives by filename — and for
      negatives it resolves the filename index back to **the phrase that was
      actually said**, since `record_samples` writes one file per prompt. The
      difference between "some negative is confusable" and "it struggles with
      'Hey Pierre', record a few more of those".

### Round 15: keep the personal model out of the repository (2026-08-30)

Prompted by the user asking whether to push their recordings. The answer was
no — `data/wakeword/samples/` was already gitignored — but the question
surfaced a real problem behind it: `train` wrote to
`data/wakeword/hey_peer.onnx`, which **is** tracked. So a personalised run
silently modified a committed file, and a later pull or checkout would
clobber the model someone had just trained on their own voice. (I hit this
myself while testing and had to restore it.)

- [x] Training now writes `data/wakeword/hey_peer_user.onnx`, already covered
      by the existing `data/wakeword/*.onnx` ignore rule.
- [x] `default_model_path()` prefers the personal model when present and
      falls back to the shipped generic one. Two files rather than one gives
      both properties: a fresh clone runs, and whoever records their voice
      gets their own model used automatically with nothing to configure.
- [x] `evaluate` defaults to the same resolution, so it scores whichever
      model the app would actually load rather than a fixed path.

### Round 16: model-generated text must not be able to kill the app (2026-08-30)

First live run of the personalised model: **the wake word fired correctly**,
then the app crashed with
`UnicodeEncodeError: 'charmap' codec can't encode character '\u2011'`.

U+2011 is a non-breaking hyphen, and it came from Nemotron — the clarifying
question added in round 11 (`ask`) is printed straight to the console. The
project already had a rule that console strings are plain ASCII, after
mojibake in MINGW64; what changed is that some of what gets printed is now
**model output**, whose characters are not ours to choose. Printing it on a
cp1252 Windows console raised, and the exception unwound the whole turn loop.

- [x] `_log` can no longer raise: on `UnicodeEncodeError` it re-encodes with
      replacement. A mangled character is cosmetic; losing the session over
      one is not.
- [x] `main()` reconfigures stdout/stderr to UTF-8 with `errors="replace"`
      where the streams support it, so the same protection covers every other
      `print` in the app rather than just this one path.

Reproduced the exact failure against a real cp1252 stream and confirmed the
character now prints as a placeholder instead of raising.

### Round 17: keep exotic typography out of the prompt, and out of what comes back (2026-08-30)

Follow-up to the `\u2011` crash, on the user's point that prompt engineering
should avoid characters that are fragile to encode. The technical reason is
stronger than caution alone: **models mirror the typography they are shown**.
A prompt written with em dashes invites em dashes in the reply — and it is
the reply that gets printed to a console and read aloud. The prompt was
demonstrating exactly the characters we did not want back.

- [x] `SYSTEM_PROMPT` is now pure ASCII (it held an em dash and accented
      French in its examples), verified by a test rather than by eye.
      `VERIFY_SYSTEM_PROMPT` already was.
- [x] The prompt asks explicitly for plain ASCII punctuation in the reply,
      and says why: the strings are printed and spoken, and a Windows console
      on a legacy code page cannot encode them.
- [x] `_plain_punctuation` maps typographic characters to plain equivalents
      on the way out, because an instruction is not a guarantee. Applied to
      the clarifying `question` only — **filenames are left byte-exact**,
      since they have to match real files on disk, and a file may legitimately
      contain any character.
- [x] Accents are deliberately kept: they are correct French, Piper needs
      them to pronounce words properly, and the console path handles them
      safely since round 16. Only characters with no value beyond typography
      are replaced.

Three layers, none sufficient alone: an ASCII prompt makes exotic output
unlikely, the instruction makes it rarer, normalisation catches what still
gets through, and round 16's unfailing `_log` means even that cannot crash
anything.

### Round 18: latency — the voice arriving late (2026-08-30)

Everything works; the complaint is timing, with the spoken narration the
worst of it.

- [x] **PortAudio was being initialised once per utterance.** Both
      `tts.speak` and `play_activation_chime` constructed their own
      `pyaudio.PyAudio()`, played, then `terminate()`d. That constructor
      initialises PortAudio and enumerates the host API's devices — a few
      hundred milliseconds on Windows, sometimes more — and it sat squarely
      between deciding what to say and the first sample coming out, which is
      exactly what "the voice arrives late" describes.
      New `heypeer/tray/audio_out.py` holds one process-wide instance and
      serves both callers. Streams are still opened per playback: that is far
      cheaper than initialising PortAudio, and keeping an output stream open
      would claim the device for no reason. Playback is serialised with a
      lock, since the chime plays from the audio thread and speech from the
      turn handler and PortAudio is not reliably safe across concurrent
      stream operations — they don't overlap in practice, so this costs
      nothing.
      **Not measurable here** (no audio device in this sandbox, pyaudio isn't
      even installable), so this is reasoned from the API's documented
      behaviour rather than profiled. The user's ear is the measurement.
- [x] **TTS warm-up on preload**: the voice was loaded ahead of time but the
      first `synthesize_wav` and the first PortAudio init still landed on the
      first thing Hey Peer said. `preload()` now also warms PortAudio and
      synthesises one throwaway phrase.
- [x] **Stop transcribing silence we chose to wait through.** End-pointing
      holds on for ~1.2s of quiet before deciding the instruction is over,
      and that silence was then handed to Whisper, whose cost scales with
      audio length. `_record_instruction` now trims the trailing quiet
      before returning, keeping a 3-chunk margin so a soft final consonant is
      never clipped.
      Adjusting the trailing-silence *threshold* was the other option and was
      deliberately not taken: 0.8s is the value that cut real instructions in
      half two rounds ago, and trimming afterwards gets the latency back
      without reopening that.

### Round 19: the latency fix broke comprehension - reverted, and an older bug found (2026-08-30)

Latency was fixed, but nothing could be understood any more. Reading the
logs, Nemotron was behaving *correctly* - it asked exactly the right
questions ("Vers quel dossier ?"). The transcripts arriving were truncated:
"Deplace le fichier.", "Deplace le fichier 15-". The regression was upstream,
and it was mine.

- [x] **Reverted the trailing-silence trim from round 18.** "Quiet" there
      means below the speech threshold, and the end of a spoken sentence
      routinely trails off below it *while still being speech*. Trimming
      deleted those words. It saved roughly 0.1s of Whisper input and cost
      the instruction - a plainly bad trade, especially now that the real
      latency win (sharing one PortAudio instance) had already landed.
- [x] **Found why the ends of sentences were being classified as silence at
      all**: the adaptive speech threshold added in round 4 had never
      actually worked. `_record_instruction` measured the room's noise floor
      from `self._prebuffer` — but the caller clears the prebuffer just
      before calling it, so it always saw an empty list and silently fell
      back to a fixed -40 dBFS. Every measurement, every room, always the
      same cutoff.
      The floor is now measured by the caller *before* clearing and passed
      in. Measured effect: a quiet room now yields a -50 dBFS threshold
      instead of -40, so a sentence trailing off at -45 dBFS is kept as
      speech rather than cut.

Worth noting how this one hid: the fallback value was chosen to be a sane
default, so the broken path produced plausible behaviour rather than an
obvious failure. It only became visible once a *second* change started
deleting the audio that the too-high threshold had mislabelled.

### Round 20: synonyms, and a genuinely continuous blob (2026-08-30)

- [x] **"bouge le fichier A vers B" was not understood.** The user asked
      whether the request even reaches an AI. It does — `interpret_text`
      sends it to Nemotron — so the failure is more interesting than a
      missing keyword: the prompt listed exactly **one** verb per action
      ("deplace", "renomme", "supprime"), and a small model anchors hard on
      its examples rather than generalising from them. Fixed by saying
      outright that the verbs are examples and not a vocabulary, and listing
      the common French alternatives (bouge, mets, range, transfere, vire,
      efface, rebaptise, "reviens en arriere"...). A prompt defect, not a
      comprehension one.
- [x] **The blob was stepped, and now moves continuously.** The cause was
      structural: frames were pre-rendered into a short loop and cycled at
      one frame every 0.28s — about 3.6fps of actual shape change, however
      often the window was updated. Pre-rendering existed because drawing a
      frame cost ~18ms (polygon fill at 3x supersample, then a gaussian
      blur).
      Replaced with an **analytic radial field**: for each pixel, its angle
      gives the outline's radius there and its distance decides body, edge or
      glow. Measured at ~1.4ms a frame, so every frame is now rendered live
      at 30fps from continuously varying parameters. Antialiasing and the
      glow fall out of the field itself rather than being approximated.
- [x] Implemented the requested design properly:
      - `R(theta) = R0 * (1 + A * N(theta, phase))`, with `N` a sum of low
        harmonics drifting at mutually irrational speeds. Band-limited **by
        construction**, so the outline can never develop a spike or corner
        however hard the amplitude is driven — asserted by a test, since it
        is the property the whole look depends on.
      - Four states as specified: idle breathing at ~3%, listening more
        irregular with a lifted halo, speaking driven by amplitude with lobes
        forming and dissolving, and a smooth return toward a near-sphere.
      - The transition is not a special case: every animated quantity
        (amplitude, speed, glow, radius) is *eased* toward its target, which
        settles in roughly half a second — the design's 400-700ms — and makes
        a visible jump impossible whatever changes.
      - The noise phase is **accumulated**, not derived from wall-clock time.
        Evaluating `sin(k*theta + speed*t)` would make any change of speed
        rewrite the phase and teleport the shape; accumulating bends the
        motion instead.
      - Voice drives energy far more than size, as specified: level mostly
        raises amplitude, churn speed and glow, and only slightly the radius.
      - Palette exactly as given: cyan #7DD3FC, blue #2563EB, violet #7C3AED,
        radial with the cyan off-centre toward the top for volume.
- [x] Deleted `blob_points`, left over from the window-region era and now
      used only by its own tests.

### Round 21: four reasons the blob looked inert (2026-08-30)

All four reported symptoms were real, and two were bugs my own tests were
passing straight over.

- [x] **"Trop bleu, le violet n'a pas ete pris en compte."** Correct — and
      not a palette problem. The gradient was normalised over the whole
      **frame** while the blob occupies only its middle: inside the shape the
      gradient only ever travelled from 0.27 to 0.58, and violet lives at
      1.00, so it was never reached at all. Now normalised over the blob's
      own extent (distance from the off-centre highlight to its far side).
      Measured after: the most violet pixel in the shape is (121, 58, 236)
      against a target of (124, 58, 237).
- [x] **"Les mouvements sont quasiment inexistants."** `amplitude` was
      dividing the harmonic sum by the *sum of the weights*, but sinusoids at
      unrelated phases almost never align, so it delivered a measured **78%**
      of what was asked. Normalising by the sum's actual peak makes the
      number mean what it says.
- [x] **"Lorsque je parle aucun deplacement s'opere."** The level was
      arriving; it just never reached the shape in a visible amount. Two
      causes: the gains were far too timid (the radius term moved the outline
      by **1.5%** at speaking volume), and the level was smoothed once on its
      own and then a *second* time through the slow state easing, damping
      speech dynamics into nothing. Gains raised, and the voice contribution
      is now added on top of the eased state parameters rather than being
      eased again. Measured: +31% solid area and 4x churn speed from silence
      to full level, under test so it cannot quietly regress.
- [x] **"Le blob sort de l'ecran quand Hey Peer demande une reformulation."**
      He is right that this is wrong: the exchange is still open and waiting
      for an answer. The indicator hid because the turn had ended, ignoring
      that a follow-up window was armed. New `awaiting` state, visible and
      mic-reactive, held for the length of that window and then stood down by
      a timer — guarded by a generation counter so a stale window can't hide
      the indicator out from under a turn that has since started.

Also had to shrink the base radius (0.30 -> 0.26 of the frame) so the larger
deformations and the glow still fit; a halo clipped by the edge of the bitmap
would show as a straight line across it. Asserted for every state at full
level.

### Round 22: a one-line import that segfaulted the app (2026-08-30)

`python -m heypeer.main --cli` died with `Segmentation fault` — a native
crash, not a Python exception. Cause: in the previous round I added

    from heypeer.wakeword.listener import FOLLOWUP_WINDOW_SECONDS

at module level, to reuse one constant. `listener` pulls **onnxruntime and
openwakeword**, and `heypeer.main` is re-imported inside the overlay's child
process by multiprocessing's spawn — so those native runtimes were being
loaded twice, in two processes, alongside PortAudio and GDI. It also undid
round 9's lazy-import work: startup went from 0.44s to **1.03s**.

- [x] Import moved inside `_arm_followup`, where it is used. Startup back to
      0.48s, and neither runtime is loaded until voice actually starts.
- [x] **`tests/test_startup_imports.py`** asserts that importing
      `heypeer.main` — and separately the overlay module, which the child
      re-imports — pulls in none of onnxruntime, openwakeword, faster_whisper
      or piper. Verified the guard by reintroducing the bad import: it fails
      with the offending names.

Worth recording why this slipped through: an import line is invisible in
review, costs nothing locally where the libraries are already warm, and
fails on someone else's machine as a crash with no traceback. The project
had already decided these imports must be lazy (round 9, for startup time);
what it lacked was anything that would *notice* when that decision was
quietly reversed. That is now a test rather than a habit.

### Round 23: cut the app back to voice-to-action (2026-08-30)

Reported: the cursor colouring is unwanted, the program feels slower, the
blob still doesn't move while speaking, recording should not begin until the
blob has arrived, and all the skills/monitoring machinery should go.

- [x] **Deleted skill learning and activity monitoring outright** — not
      disabled behind a flag this time. Gone: `heypeer/patterns/` (detector,
      memory, skill), `heypeer/capture/` (input hooks, active-window polling,
      file watching), `SkillRunner` and its pyautogui replay, the `run_skill`
      intent branch, and the `learn_skills`/`capture_input` settings. Five
      test modules went with them.
      Also dropped five dependencies that nothing imports any more: pynput,
      pywinctl, watchdog, pyautogui, opencv-python.
- [x] **Removed the coloured mouse cursor** (`heypeer/tray/cursor.py`), which
      was several hundred lines of win32 bitmap surgery serving one visual
      hint the user did not want.
- [x] **Recording now starts only once the indicator is on screen.** This was
      also the answer to "it doesn't move when I speak": verification used to
      run *concurrently* with recording, so the chime and the blob only
      appeared once recording was already well under way — by which point the
      user had usually finished the sentence. The blob genuinely never had
      any voice left to react to.
      Now sequential: verify -> chime and blob together -> wait out the
      slide -> record. The cue means "speak now", which is both what was
      asked for and how a responsive assistant behaves. Under test.
      The concurrent design existed to avoid losing a few hundred
      milliseconds of speech for users who run the wake word straight into
      the instruction. That trade was wrong: it bought audio nobody could use
      and cost the entire visual feedback loop.

Startup is 0.49s with none of onnxruntime, openwakeword, pynput, pywinctl,
watchdog or pyautogui loaded. Verified a full turn end to end afterwards,
including "bouge 4 vers test" (the synonym from last round) and undo.

### Round 24: the blob arrived long after the cue (2026-08-30)

The chime is now instant - the shared PortAudio instance did its job - but
the blob still landed well after the user had started speaking, so there was
no way to tell whether it reacted to their voice at all.

Measured rather than guessed: rendering a frame costs 1.73ms including the
premultiply, so drawing was never the problem. Two other things were.

- [x] **The slide eased by a fixed fraction per frame**, which made its
      duration hostage to the frame rate: 18 frames is 0.60s at 30fps but
      1.20s at 15 and 2.25s at 8. Any hitch in the loop - GDI, the desktop
      compositor, another process - stretched the cue proportionally. It is
      now interpolated on **elapsed time**, so it takes 0.28s whatever the
      frame rate, with an ease-out that covers most of the distance early.
      Extracted as `slide_position` so the property is under test at 8, 15,
      30 and 60fps rather than assumed.
- [x] **The child polled its command queue every 0.1s while idle**, so a
      "show" waited out up to a full interval before anything began. It now
      blocks on the queue with a timeout and reacts the instant the message
      lands.
- [x] Two smaller things on the same path: the geometry and colour caches
      and the GDI surface are built when the child starts rather than on the
      first visible frame, so the cue doesn't pay for setup at the exact
      moment it needs to feel immediate; and the loop now sleeps the
      *remainder* of a frame rather than a whole interval on top of the work
      already done, which had put the real frame rate permanently below the
      nominal one.

`INDICATOR_SLIDE_SECONDS` (how long the listener waits before recording) now
matches the slide at 0.30s, so "blob on screen" and "Hey Peer is listening"
stay the same moment.

### Round 25: the chime now lands with the blob (2026-08-30)

Requested: sound the cue once the indicator has arrived, rather than before
it. Straightforward, except for one thing worth noticing — playing the beep
at the instant recording starts means the **mic records the beep**, which
would also confuse the energy-based end-pointing.

- [x] `on_ready` fires after the slide and immediately before the mic opens,
      so anything it does lands exactly on "speak now". The chime is played
      **synchronously** there: it is the cue, so recording must begin after
      it, not during it.
- [x] The chime asset was 0.66s, which as dead time before the user may
      speak is too much. Its energy is heavily front-loaded — measured 90%
      within the first 0.29s, the rest an inaudible decay — so it is trimmed
      to 0.32s with a short fade to avoid a click. 90% of the energy kept.
- [x] `play_activation_chime(blocking=...)`, since the two call sites now
      want opposite behaviour and the difference matters.

Sequence: "Hey Peer" -> verification -> blob descends (0.30s) -> chime
(0.32s) -> mic opens. One unambiguous cue instead of a sound followed a
moment later by something appearing.

### Round 26: a method that was wired up but never written (2026-08-30)

The listener thread died on first use with
`AttributeError: 'HeyPeer' object has no attribute '_on_ready_to_listen'`.

Last round's edit came in two halves: wire `on_ready=self._on_ready_to_listen`
into `listener.start`, and add the method it refers to. The first landed; the
second silently did not, because the text it was anchored to had already
changed. So the app shipped calling a method that does not exist.

- [x] Added the method, and moved the chime into it — the change round 25 was
      supposed to make. Verified the resulting sequence end to end:
      `blob:recording -> chime(blocking=True)`, with the listener's 0.30s
      wait between them.
- [x] **Covered the gap that let it through.** No test exercised
      `_run_wake_listener`: every other test calls `on_wake_word` directly,
      so the wiring between `HeyPeer` and the listener was untested
      end-to-end. There is now a test that patches `WakeWordListener` and
      asserts every `on_*` callback handed to `start()` actually exists and
      is callable, plus one that a missing model degrades to a message rather
      than an unhandled traceback in a background thread. Confirmed by
      deleting the method again and watching the test fail with the user's
      exact AttributeError.

This is the second time in three rounds that a scripted edit half-applied
without complaint. The lesson is not "be more careful" — it is that wiring
between components needs a test that instantiates it, because a name that
only resolves at call time, on a background thread, will otherwise be found
by the user rather than by me.

### Round 27: a conversation, a sphere, and the first "Hey Peer" (2026-08-30)

Three reports: the first activation after launch is usually missed, the beep
still arrives before the blob, and the blob is well animated but flat - "je ne
percois pas vraiment de profondeur spherique". Plus a direction for the
system prompt: Hey Peer will grow to dozens of use cases, including questions
that have nothing to do with the computer, so a turn has to be *interpreted*
into "act" or "answer", and an exchange should end when the discussion is
over or the task is done - the way Siri and Alexa handle it.

**The first "Hey Peer" was not missed. It was answered several seconds late.**
Verification runs on the microphone thread, and Whisper's verification model
is still loading in the background for the first several seconds after
launch. Asking a cold model to transcribe there did not merely add latency:
it stopped the mic being read for the whole load, so Hey Peer was deaf
exactly while the user was speaking to it, then finally responded long after
they had repeated themselves.

- [x] `stt.is_loaded()`, and `_verify_wake_word` skips verification rather
      than waiting when the model is cold. The detector's own judgement
      stands for that one activation; the full-transcript check in
      `_interpret_audio` still rejects it if the wake word was not there.
- [x] A lock around model construction - `preload` and the wake thread could
      previously build the same WhisperModel simultaneously, on the machine
      that was trying to answer a wake word.
- [x] "Hey Peer est pret" printed when the models finish warming, so that
      window is visible rather than inferred from odd behaviour.

**The beep was scheduled off a duration that could not know the answer.** The
slide is 0.28s, so the chime was fired 0.30s after asking for the blob. But
the slide only *starts* once the overlay process has woken from its queue and
drawn a frame - the real time to "on screen" is that wake-up plus the slide,
which is routinely more than 0.30s.

- [x] The overlay child now sets a `multiprocessing.Event` while the blob is
      fully down, and `DebugWindow.wait_until_visible` waits on it.
      `_on_ready_to_listen` waits for the real landing, then chimes. The
      listener's `ready_delay` argument is gone: a fixed duration was the
      wrong shape of answer.
- [x] A stalled overlay costs a visual, not a turn - it chimes anyway after
      0.8s.

**Flat because the shading was painted in frame space.** The colour was a
radial gradient measured from a fixed point on the *bitmap*, cached because
it depended on nothing that moved. A disc with a gradient on it.

- [x] Rewrote it around a **surface normal**. The blob is treated as a sphere
      whose silhouette is the animated outline; the normal gives diffuse
      shading (the hue itself follows the light, so the ramp wraps round the
      form), a tight Blinn-Phong specular, a Fresnel rim, and ambient
      occlusion for the dark shoulder between the lit face and the glowing
      edge. 3.8ms/frame, 11% of the 30fps budget.
- [x] The rim is a hue-preserving lift, not a blend toward cyan. Blending
      repainted the shadowed silhouette the colour of the lit one, which was
      most of why the blob still read as uniformly blue: violet went from a
      thin crescent to 27% of the body.
- [x] Five tests for the depth, including that the highlight sits at the same
      place *on the sphere* at any radius - which the old frame-space
      gradient fails by construction.

**From command line to conversation.** New `reply` action and an `end_turn`
flag on every answer; `HeyPeer` keeps the exchange's turns and replays them,
clearing them when it closes. `ask` holds the exchange open regardless of
what the model says, since a question that ends the turn is self-contradictory.
The prompt is reorganised around deciding *what kind of turn this is* before
choosing a form, and states plainly that the action list will grow and that
anything unsupported must be answered, never bent into the nearest file
action.

Two failures found against the **live endpoint**, not by reading the prompt:

- With "supprime le 15" in the history, a plain "non merci" came back as
  `delete_file 15.txt` **again** - the sign-off read as a repeat of the last
  command. The conversation memory had introduced a way to perform an action
  twice that nobody asked for once. Fixed by stating that the history is
  context and not a queue of work, and that only the newest turn can request
  an action.
- "quelle heure il est" -> *"Il est 14h"*, invented. It has no clock. Fixed by
  naming what it cannot see and saying that making one up is worse than
  admitting it.

Both now behave, verified live, along with "ouvre Spotify" -> *"Je ne peux pas
ouvrir Spotify pour l'instant."* and the three-turn continuation
`"deplace la facture"` / *"Vers quel dossier ?"* / `"dans Archives"` ->
a real move of `facture_mars.pdf`.

The lesson worth keeping: the two real bugs this round were both in the
*model's* behaviour, and neither was visible from the prompt text or from any
mock. Exercising the live endpoint across a handful of adversarial turns took
two minutes and found both.

### Round 28: the voice was being handed phonemes it had never heard (2026-08-31)

"la voix [...] trop peu realiste et comprend mal des anglicismes ou des
extensions de fichier". Two complaints in one, and only one of them is
diagnosable from a machine with no speakers.

**The diagnosable half was a real defect, not a matter of taste.** Piper
phonemizes through espeak-ng, and espeak switches language per word: handed
"Spotify" mid-French-sentence it emits English IPA, `spˈɒtɪfˌaɪ`. `ɒ` and `ɪ`
do not occur in French. The French voice has an embedding for them - the
phoneme table is shared across all Piper voices - but was trained only on
French speech, so it has never heard one. The output is whatever an untrained
embedding happens to produce.

File extensions failed the same way from the other side: espeak reads some
correctly (`4.txt` -> "quatre point te ixe te") and mangles others
(`script.py` -> "pi", `rapport.docx` -> "docks", `config.json` -> a consonant
cluster with no vowel), depending on whether the letters happen to look like a
word to it.

- [x] `heypeer/tray/pronounce.py`: extensions spelled out deterministically,
      and a respelling table for the words that leak.
- [x] Three cleverer fixes were tried first and none work. Piper's espeak
      bridge is a compiled extension exposing three functions: SSML
      (`<voice xml:lang="fr">`) comes out read aloud word by word, espeak's
      `[[phoneme]]` escape is spelled out letter by letter, and there is no
      flag to disable language switching. The input text is the only lever.

**The tests decide by phonemes, not by ear.** Ordinary *accented* French prose
is phonemized to derive the set of sounds French actually uses; every sentence
Hey Peer says must, after respelling, stay inside it. The pairing matters:
the same sentences are asserted to *fail* untreated, so the fix cannot pass
vacuously. Two further tests guard the table in both directions - each entry
must fix a real leak, and must not introduce one.

That second guard immediately earned its keep: it rejected my "youtube" and
"playlist" entries. espeak already keeps both in French (`jˈu tˈyb`,
`plɛlˈist`), which is how a French speaker says them. I had added them by eye,
which is exactly the mistake the test exists to catch. Also rejected
"spotifaie" - it looks French and phonemizes as `spˈɒtɪfˌaiː`, entirely
English. "spo-ti-fai" is the spelling that works.

**The undiagnosable half is now decidable by the person with ears.**
`python -m heypeer.tray.tts --demo` renders the same four lines through every
French voice and speaker into `data/tts_demo/`; the choice goes in `.env`.
Piper's French ceiling is `medium` - re-checked against the published list,
there is no `high` French voice - so this is the range available without a
much heavier engine.

Found while writing it: `_get_voice` cached a single global voice regardless
of the name asked for. Harmless while there was only ever one, wrong the
moment `--demo` renders several.

### Round 29: the first thing that is not a file (2026-08-31)

"nous allons implementer l'ouverture d'appli etc. Commencons par spotify. Je
souhaite pouvoir dire hey peer lance spotify et ca ouvre spotify et lance play.
ou alors lance X par Y sur spotify et ca joue ce son"

Two requests that look alike and are not. Starting an app is one mechanism;
playing a named track is another, and neither is the other's special case.

**Apps come from a registry, not from the model.** `executor/apps.py` resolves
a spoken name against a table (exact, then alias, then fuzzy, all accent- and
case-insensitive) and refuses anything it does not recognise. This is the
whole design decision: every name on this path started as a speech transcript
and then passed through a language model, so "run whatever it said" is handing
a model's output to the shell. "Ouvre Machin" costs one turn to decline.
Launching prefers a URI scheme (`spotify:`) over an executable, because the OS
resolves a URI to whatever build the user actually installed - Store app or
desktop - where an executable name only finds one of them.

**"Lance Spotify" means start it and play.** Opening the app does not start
music; the user is left in silence looking at a player that has not begun. So
Spotify's branch opens the app, waits for it to come up, and sends the system
media play/pause key - a key the OS routes to whatever is playing, which needs
no permission from Spotify at all. The wait is the load-bearing part: pressing
play before there is a player to press it on does nothing.

**"Lance X par Y" resolves the track first.** Spotify's search takes an
*application* token - the client-credentials flow - so there is no login
prompt, no OAuth redirect, no Premium requirement and no access to anything of
the user's. It returns a track id, and `spotify:track:<id>` handed to the
desktop app plays it. Playback deliberately does not go through the Web API's
`/me/player/play`, which would need user OAuth *and* Premium.

Without credentials it falls back to `spotify:search:<query>`, which opens the
results and plays nothing. That difference is reported out loud rather than
smoothed over: announcing music that is not playing is a lie the user hears
immediately, as silence. `find_track` returns None for every way this can
fail - no credentials, no match, network error - because they all lead to the
same fallback.

One search serves both the URI and the sentence. An earlier draft had
`search_track` and `describe_track` as separate functions, i.e. two round
trips in front of someone waiting for music.

Verified against the live model - the "lance" disambiguation is the part that
could have gone wrong, since it is the same French word for all three:

    "lance spotify"                  -> open_app   Spotify
    "lance Alright par Kendrick
       Lamar sur spotify"            -> play_music "Alright Kendrick Lamar"
    "lance le fichier 4 dans
       Archives"                     -> move_file  4.txt -> Archives
    "ouvre Machin"                   -> open_app   Machin  (refused locally)

The two rounds meet, incidentally: "Je lance Spotify" is spoken as
"spo-ti-fai" thanks to round 28, instead of with English phonemes the French
voice has never heard.

Known gap: a track or artist name is unbounded English vocabulary and cannot
be respelled the way a fixed list of app names can, so "Alright, de Kendrick
Lamar" is still read with whatever espeak decides.

### Round 30: three fixes to app launching (2026-08-31)

**The turn did not end.** "le blob et heypeer restent eveille alors que le
lancement de spotify marque la fin de la requette" - and the user's own
diagnosis was right: the follow-up window was being held open *over the music
Hey Peer had just started*, which through a headset it then heard as speech.

`open_app`, `play_music` and `search_web` now arm no follow-up. That is the
whole fix: `on_wake_word` already closes the exchange and hides the blob for
any turn that armed nothing, so "end the turn" is spelled by not arming one.
My first attempt called `_close_exchange()` explicitly in each handler, which
was redundant with a mechanism that was already there.

The one case on this path that is *not* the end of the request stays open: an
app Hey Peer does not recognise, since it just said so and a rephrasing is
expected.

**"Je lance le titre par l'artiste".** Two changes. `find_track` returns a
`Track` rather than a tuple, so the sentence is built from the *resolved*
track - the model writes its `speech` before anything has been looked up, so
it can only repeat what the user said, and naming what was actually found is
how they notice the search matched something else. And the model's narration
is now ignored for this action rather than preferred over it.

**"Il oublie de lancer le titre en haut de la recherche."** This is the
no-credentials fallback, and it cannot play anything - `spotify:search:` opens
results, and there is no documented, credential-free way to resolve a query to
a Spotify track id. Approaches considered and rejected: the web player's
undocumented anonymous-token endpoint (fragile and not ours to use), and
driving the desktop UI by keystroke to hit the first result (the pyautogui
skills machinery was deleted from this project for good reasons).

So the fix is honesty plus a shove: "no credentials" and "found nothing" are
now different sentences, and the first prints a one-time setup hint. Saying
"je n'ai pas trouve" when the truth is "I am not configured to search" sends
the user off trying to pronounce the title better.

**More apps, and web search.** The registry goes from 10 to 22 (Discord with
its URI scheme, Edge, Slack, Teams, Zoom, WhatsApp, Telegram, VLC, Word,
Excel, PowerPoint, Outlook, Parametres) and there is a `search_web` action.
The query is percent-encoded into a fixed search URL rather than the model
being asked for an address: a search string can say anything, a URL can *go*
anywhere, and the difference matters when the text came out of a microphone.

Verified live, including the cases that could have gone to the wrong action:

    "lance Starman de David Bowie"    -> play_music "Starman David Bowie"
    "cherche la meteo sur internet"   -> search_web "meteo demain"
    "ouvre discord"                   -> open_app   Discord
    "quelle heure est-il ?"           -> reply      (not a web search)

**Every French line I added last round was unaccented, and audibly wrong.**
Not the English-phoneme failure of round 28 - these stay in French and become
a *different French word*: "reussi" is `ʁøsˈi` where "réussi" is `ʁeysˈi`,
"precis" takes a schwa where "précis" has an é, "trouve" is the present tense
where "trouvé" is the participle. I had carried the prompt's ASCII-only rule,
which exists for the model, into Hey Peer's own speech, where it does not
belong.

Two tests now read the spoken lines straight out of `main.py` by AST, so this
covers the whole app rather than a list that drifts: one asserts every line
stays within French after respelling, the other that none contains a word from
a list of accent traps. The phoneme test cannot see the second class, which is
why there are two. Both were confirmed by putting the bad line back.

That first test also caught "PowerPoint", which espeak reads half in each
language - `pˈaʊə pwˈɛ̃`, English "power" glued to French "point".

### Round 31: a prompt that refused what the app had just learned to do (2026-08-31)

"pourquoi la question de la meteo ne fonctionne pas ?" - Hey Peer answered
"Je ne peux pas consulter la meteo, je n'ai pas acces a cette information",
one round after gaining a web search.

The prompt said both things at once. Two paragraphs, written before
`search_web` existed and never revisited when it shipped:

    You cannot see the clock, the calendar, the weather, the web, the
    screen [...] Asked for one of those, say you cannot check it.

    When the user asks for anything else - open an application, send a
    message, search the web, change a setting - [...] say plainly and
    briefly that you cannot do that yet.

So the prompt described `search_web` and `open_app` as supported near the
top, and refused both further down. The older lines are the more specific
ones, and they won.

**This is the failure mode of a prompt that grows by appending**, and it is
worth naming: every new capability gets described twice, once where it was
added and once in whatever "here is what you cannot do" text predates it. The
second description is invisible while writing the first.

- [x] Replaced the refusal with an ordered decision: do I know this ->
      answer; is it about this machine or this moment -> say I cannot check;
      otherwise -> search. The anti-hallucination rule it was protecting is
      intact - "Il est 14h" invented on the spot is still forbidden.
- [x] `speech` for a search must say it is opening one. The model's first
      draft was "Voici la meteo a Paris", which is a promise the browser has
      to keep; the action opens a page and tells the user nothing.
- [x] The stale "cannot do yet" list now names things Hey Peer genuinely
      cannot do (send a message, change a setting, edit inside a file).

**Measured rather than eyeballed.** Prompt changes are behavioural and the
model is stochastic, so a single sample proves nothing - the first two
rewrites both looked fine on one pass and scored identically at 45/50 over
five. Ten instructions, eight runs each:

    meteo a Paris          search_web  8/8
    score du match         search_web  7/8   (1 "ask" - which match?)
    heure de fermeture     search_web  8/8
    cherche des recettes   search_web  8/8
    quelle heure est-il    reply       5/8
    comment ca va          reply       8/8
    capitale du Perou      reply       4/8
    supprime le fichier 4  delete_file 8/8
    lance Starman          play_music  8/8
    lance spotify          open_app    8/8

The complaint is fixed at 8/8 and nothing regressed. The two that split are a
genuinely fuzzy boundary - opening a browser for the time, or for a fact the
model knows, is a worse answer but not a wrong one - and I stopped tuning
rather than over-fit a small model to ten sentences.

**The test found more than it was written for.** It slices the prompt's
refusal section and asserts nothing reachable is named there; that is how
"open an application" turned up, still refused two rounds after shipping. The
guard now checks the whole capability list, so the next action cannot be
added without the contradiction surfacing.

Also: three prompt tests asserted on exact line breaks and broke every time a
paragraph was re-wrapped without its meaning changing. They normalise
whitespace now.

### Round 32: a track that landed without playing (2026-08-31)

"par moment lorsque je dis de lancer un titre, heypeer se met bien dessus
mais oublie de lancer la lecture" - intermittent, which was the clue.

The same gap `launch_and_play` already exists to close for "lance Spotify"
itself, one level down. Opening a `spotify:track:` URI in an *already-running*
Spotify plays it immediately - the same as clicking a spotify: link while the
app is open. Opening one while Spotify is *closed* cold-starts the app, which
comes up showing the track paused, exactly like plain "lance Spotify" does not
start music on its own. "Par moment" is "whenever Spotify happened not to
already be open" - most requests land after an earlier "lance Spotify" or a
previous track, which is why it looked occasional rather than constant.

`apps.is_running()` (Windows `tasklist`, no new dependency) checks before
opening the URI. `spotify.play_track()` presses play only on a cold start; an
already-running Spotify is left alone, because pressing play there would
TOGGLE an already-playing track *off* - the fix has to know which case it is
in, not just fire unconditionally. `play_uri()` stays a pure "open this" for
the two search-result fallbacks, where there is nothing to press play on.

Confirmed the tests actually distinguish the two branches, not just record
calls: `test_an_already_running_spotify_is_left_alone` asserts nothing but the
open call happens (no press), `test_a_cold_started_spotify_gets_a_settle_
then_a_press` asserts the full open-wait-press order.

**Found while fixing it: three tests in `test_main.py` were coupled to
whatever happens to be in the developer's own `.env`.** They asserted the
"credentials missing" branch by relying on the real environment having no
Spotify keys, rather than mocking `credentials_missing`. The moment real keys
were added to test on real hardware, one of those tests started silently
exercising the wrong branch - passing by observing the wrong thing rather than
failing, since the resolved-track path also produces search-shaped assertions
by coincidence in enough cases to not be obviously wrong. Fixed by mocking
`credentials_missing` explicitly, so the test is about the app's behaviour,
not about the tester's machine.

The same detour also caught three tests genuinely sleeping 2.5 real seconds
each - `play_track`'s settle wait, unpatched, running for real because they
patched `play_uri` instead of `play_track`. Switched them to patch
`play_track` directly, which is also the more accurate thing to assert: that
is the function `main.py` actually calls, and `play_track`'s own cold-start
logic is already covered on its own in `test_spotify.py`.

### Round 33: "ouvre discord" did not open Discord (2026-08-31)

Reasoned from how Windows installers and `ShellExecute` actually behave -
not observed, there is no real Windows box here - but the diagnosis holds
together on three separate points, any one of which alone would explain it:

1. `discord:` was tried as a URI scheme, the same mechanism that genuinely
   works for Spotify. But Spotify's scheme is documented and used all over
   the web ("Open in Spotify" links); Discord's was never verified to be a
   real, registered system protocol the way Spotify's is - it was a guess
   that looked plausible next to a working one.
2. Discord installs to a per-user, versioned folder under `%LOCALAPPDATA%`
   that is never added to PATH, so a bare `"discord"` executable name was
   never going to resolve.
3. The Windows-path fallback pointed at `Update.exe` (Squirrel's installer/
   updater, which is what Discord and several other apps in the registry
   actually use to self-update) and called it with no arguments. Squirrel
   apps need `--processStart Discord.exe` to actually launch the app -
   `os.startfile` cannot pass that - so even finding this file and running
   it would have opened Squirrel's own updater UI, not Discord. Worse than
   doing nothing: it would have looked like it "worked" while doing the
   wrong thing.

**Fix**: a Start Menu shortcut search, new in `apps.py`
(`_find_start_menu_shortcut`), tried between the URI attempt and a resolved
executable path. Every Windows installer, Squirrel included, drops a
shortcut in the Start Menu specifically so the shell can find the app - a
`.lnk` already encodes the right target, arguments and working directory,
so nothing installer-specific needs to be known here. Searches both the
per-user and all-users Start Menu, recursively (some shortcuts nest in a
publisher subfolder - "Microsoft Office Tools\Word.lnk", not directly
under Programs), matching an app's name or any alias, exact first then
substring.

Also fixed while auditing the rest of `launch()`: the executable-name
attempt handed a bare string like `"discord"` straight to `os.startfile`,
which wraps `ShellExecute` - not documented to search PATH for an
extensionless name the way `subprocess`/`CreateProcess` is. It now resolves
through `shutil.which` first (`_executable_candidates`, already used
elsewhere in this file for `open_url`), so what actually reaches
`os.startfile` is a real, resolved path.

Discord's broken `Update.exe` windows_path entry is removed outright rather
than left as a fallback that "succeeds" at the wrong thing - if the Start
Menu search fails too, `launch` now fails honestly and Hey Peer says it
could not open Discord, instead of silently popping an updater window and
claiming success.

Every mechanism here is independently testable except "does this actually
launch Discord on the user's machine" - `_find_start_menu_shortcut` takes
an overridable `roots` parameter specifically so its matching logic (exact,
alias, nested subfolder, substring, a missing root) can be verified against
a synthetic Start Menu tree without a real Windows install.

### Round 34: answering in French no matter what language was spoken (2026-08-31)

"des fois je parle an anglais, le resultat est bon mais la parole qui
confirme est en francais donc pas de logique sur la reponse" - the action
taken was correct, only the spoken confirmation ignored the language of the
instruction. Reproduced live before touching anything: "how are you?" came
back correctly in English, but "delete facture.pdf", "move 4.txt to
Archives", "what's the weather in Paris?" and "open Spotify" all answered in
French regardless.

**Root cause, not a missing rule - a rule losing to eleven French examples.**
The prompt already said "answer in the language the user spoke, normally
French." Every single worked example of every action's JSON shape, though,
is phrased in French ("deplace le fichier facture...", "Je deplace..."), and
apparently that weight of example wins over one explicit sentence for
anything that is not plain conversation - "reply" alone came back correctly
because nothing anchors it to a fixed language.

**Fix has two halves - the words, and the voice.**

- The prompt now states the rule once, emphatically, right after the
  persona intro (before any French example has had a chance to anchor
  anything), restates it in "How to speak", and requires a new `"language"`
  field ("fr" or "en") on every single JSON answer - stated once, centrally,
  rather than duplicated across eleven blocks. Nemotron reports which
  language it actually used instead of the caller guessing from short output
  text afterwards (unreliable - langdetect-style heuristics are bad on a
  handful of words), since the model already knows: it just wrote the
  sentence.
- `heypeer/tray/tts.py` picks the Piper voice from that field -
  `en_US-lessac-medium`, already downloaded alongside the wake-word training
  voices, so nothing new to fetch. `pronounce.for_speech`'s anglicism
  respelling is skipped for English text - that layer exists to fix a French
  voice mangling English words, which is not a problem English text read by
  an English voice has.
- Every one of Hey Peer's own *fixed* fallback strings (an unknown app, "rien
  a annuler", a failed launch, ~15 of them across `main.py`) got an English
  counterpart, selected by a small `_bilingual(language, french, english)`
  helper - answering "I don't know the application Machin" in French when
  asked in English would have been the same inconsistency in a different
  place.

**Measured, and one edit reverted after making things worse in one
direction.** A first pass added a concrete worked example to the delete_file
and move_file blocks ("in English, answer 'Deleting notes.txt.', not
French"). It fixed the English side but dragged the *French* side down hard
- "supprime facture.pdf" dropped from a clean 6/6 to 4/12 correct across two
samples, a real, reproduced overcorrection, not noise. Lightened to a plain
alternate trigger phrase with no prescribed answer sentence, leaning on the
already-strengthened top-level rule instead - both directions landed
reasonably balanced after that (English ~83-92%, French ~92-100% across the
cases measured). Stopped there rather than keep tuning single sentences
against a small sample, the same discipline round 31 used for the weather
routing fix.

**Known, accepted gap:** an undo entry's own description ("le deplacement de
facture.pdf") is written in French at the moment the *original* action ran
and stays that way regardless of what language "annule"/"undo" is later said
in - fixing that needs the original action's language stored alongside the
entry, which nothing does yet. `_run_undo`'s own fixed sentences around it
("J'annule .../Undoing ...") do match the current turn's language; only the
embedded description does not. Left as a known limitation rather than a
deeper `UndoEntry` rewrite for a comparatively rare case (an English "undo"
of a French-narrated action).

`Track.spoken` (Spotify) became a method taking `language`, since "par" vs
"by" needed to vary too - the property syntax could not take a parameter.

365 tests.

### Round 35: system control and clipboard - beyond files and apps (2026-08-31)

Requested directly, from a wider brainstorm of "make Hey Peer a complete
product": volume, screen brightness, window management, and the clipboard -
eight new actions (`adjust_volume`, `adjust_brightness`, `maximize_window`,
`minimize_window`, `close_window`, `minimize_all`, `clipboard_copy`,
`clipboard_read`), none of them about a specific file or app any more.

**Volume and window control: the OS's own mechanisms, no new library for
either.** Volume up/down/mute are the same three multimedia keys a physical
keyboard sends, pressed via `keybd_event` - exactly `executor/spotify.py`'s
`press_play` mechanism, already established. Window control is plain
`user32.dll`: `EnumWindows` to find a window, `ShowWindow` to maximize or
minimize it, `PostMessageW(WM_CLOSE)` to close one without blocking on
whatever the app does in response. `pywin32` was deliberately not added -
this project already talks to `user32`/`gdi32` directly via `ctypes` for the
layered-window overlay, so this follows that established pattern rather than
introducing a second one. A window is found by matching its title against an
app's name/aliases - going through the *same* `apps.resolve_app` registry
`open_app` uses, so "minimise Chrome" and "ouvre Chrome" agree on what
"Chrome" means, and an app Hey Peer does not know gets the same honest
decline either way. The matching logic itself (`_match_window`) is factored
out to take a plain list of `(hwnd, title)` pairs rather than calling
`EnumWindows` directly - independently testable from this Linux sandbox, the
same split `apps._find_start_menu_shortcut` uses for the Start Menu search.

**Brightness is the one genuinely uncertain piece here**, flagged as such
rather than glossed over: `WmiMonitorBrightnessMethods` only exists for a
laptop's own integrated panel (ACPI backlight). Most **external desktop
monitors have no software brightness control at all** - they need DDC/CI, a
different, hardware-dependent protocol most Windows installs have no driver
for. This code cannot tell which situation it is in from here, so it does
not pretend to: `adjust_brightness` returns whether it actually worked, and
a `False` becomes an honest spoken "je ne peux pas régler la luminosité sur
cet écran", never a silent no-op reported as success.

**Clipboard**: `pyperclip` (new dependency - small, no transitive deps,
already solves the `GlobalLock`/format-negotiation retry logic that hand-
rolled `ctypes` clipboard access is a known source of subtle bugs in)
handles read/write; "copie ça" is a simulated Ctrl+C via the same keybd_event
mechanism, since there is no OS API to ask an arbitrary application what its
current selection is - the keystroke is the only thing every application
already understands.

"Résume ce que j'ai copié" needed a genuinely new piece of architecture:
`clipboard_read`'s classifier JSON is produced *before* the clipboard has
been read (nothing hands the classifier that content), so summarizing it
has to be a **second, narrower Nemotron call**, made only once the actual
text is available - `NemotronClient.summarize_for_speech`, with its own
short `SUMMARIZE_SYSTEM_PROMPT` ("what is this text worth saying out loud"),
not the big action-classifying one. The same reasoning `verify_screen` and
Spotify's track search already established: some things cannot be decided
until data only available *after* the classifier has run is actually in
hand. Truncated to 4000 characters before sending - someone copying an
entire document must not turn three spoken sentences into a slow, expensive
request over the whole thing.

**A real routing bug, found live, not assumed.** "Copie ça" was ambiguous
enough that the model split roughly 50/50 between correctly triggering
`clipboard_copy` and inventing a "reply" declining because "no file is
selected" - it was reasoning about `clipboard_copy` as if it needed to
verify a selection exists before acting, which it never can and was never
meant to. Measured across several phrasings and repeats before touching
anything, then again after: the fix states outright that this is a keypress
sent regardless of outcome, never a thing to refuse or ask about, and
explicitly separates it from "copie le fichier X" (naming a real file, which
Hey Peer genuinely cannot do - no `copy_file` action exists - and should
decline via "reply", not silently reinterpret as a clipboard copy). Went
from roughly half-broken to correct on every phrasing tried across three
repeats each, with one residual flake on the single most context-free
phrasing ("copie ça" alone) - the same kind of small, accepted residual
round 31 and round 34 both stopped at rather than keep tuning single
sentences against a handful of samples.

404 tests.

### Round 36: documents and the screen - and vision quietly started working (2026-08-31)

The last two of the "complete product" brainstorm: `summarize_document`
("resume facture.pdf") and `read_screen` ("qu'est-ce qu'il y a sur mon
ecran ?", "y a-t-il un message d'erreur ?").

**A real, live surprise that changed the shape of this round.** The prompt
has said since round 25 that the model cannot see the screen, because the
one time this was tried, sending an image alongside `response_format:
json_object` 400'd outright on this Nebius deployment. Re-checked before
assuming that still holds, since a hosted deployment can change without this
project knowing - and it does not hold any more: a bare `[text, image_url]`
call, and separately the exact `json_object` shape that used to fail, both
now succeed, repeatedly, including correctly reading text drawn into a test
image. `read_screen` exists because of that finding, not because it was
planned before checking.

**Document summarization needed no new prompt call at all.** `pypdf` (new
dependency, pure Python) extracts a PDF's or plain text file's text, and
that text goes straight into `NemotronClient.summarize_for_speech` - the
exact method round 35 built for clipboard summarization. Clipboard text and
document text are both just "some text worth condensing" to it; the method
never needed to know which. `documents.py`'s only real judgement call: a
scanned PDF with no text layer at all (no OCR here - a real, heavier
dependency for a "resume ce PDF" feature that does not need it) extracts to
"" the same as a genuinely empty file, and both get the same honest "rien a
resumer" - this code cannot tell them apart, so it does not pretend to.

**The screen needed one new thing**: `NemotronClient.describe_image`, a
second, narrow vision call (not threaded through the classifier prompt on
every turn - a screenshot is captured only when `read_screen` is actually
dispatched). The user's own instruction text is passed straight through as
the question, so "y a-t-il une erreur ?" gets answered specifically rather
than both it and "qu'est-ce qu'il y a sur mon ecran ?" getting the same
generic description. `executor/screen.py` captures via `PIL.ImageGrab`
(already a dependency, no new one), resized to 1280px wide before sending -
a 4K screenshot is several MB and does not obviously read text any better
than a smaller one.

**A real, recurring bug class, twice in one round.** Both new actions were
initially misrouted live: "qu'est-ce qu'il y a sur mon ecran ?" answered
"reply" with an *invented* description of the screen, because the prompt
still explicitly said "you cannot see... the screen" from round 25, written
before this action existed - the exact "prompt says both yes and no"
pattern from rounds 29/31/32, recurring a fourth time. Separately, "control
the volume" was still listed as something Hey Peer "cannot do yet", three
rounds after `adjust_volume` shipped - missed by round 32's own
`ACTION_DESCRIPTIONS`-driven guard, because the refusal used different
wording ("control" vs the guard's "change") from an exact-substring check.
Both fixed by rewriting the "cannot do yet"/"never invent a fact" sections
to route screen questions to `read_screen` and stop naming things that are
now supported at all - and by adding a second, narrower guard: a short,
explicitly-curated keyword list (volume, screen, brightness, clipboard - the
capabilities that have *actually* drifted this way, not a guess at what
might) checked the same way, catching a reworded refusal an exact-phrase
match cannot. Verified live afterward: every case that was wrong now routes
correctly, and the previously-correct cases (the weather, the time, ordinary
conversation, file actions) still do too.

429 tests.

### Round 37: a real coding agent, dispatched by voice (2026-08-31)

The flagship example from the original brainstorm: "Hey Peer analyse cette
fonction python et dis moi pourquoi elle ne fonctionne pas, puis le corrige
lui-meme dans VSCode." Two new actions - `analyze_code` (read-only,
diagnosis) and `fix_code` (writes to disk) - deliberately kept separate
rather than one action that always edits, so asking why something is broken
never risks a change nobody asked for.

**Why this dispatches to Claude Code's CLI instead of asking Nemotron to
rewrite the function.** `interpret_text` produces one JSON object per turn -
no tool access, no iteration, no way to run the code and see what actually
happens. Asking a single completion to correctly rewrite a function in one
shot is exactly the shape of task a real edit/run/verify loop exists for and
one completion is not. `executor/coding_agent.py` runs `claude -p "<prompt>"`
(Claude Code's own documented headless mode) with the watched directory as
its working directory - the same relationship Hey Peer already has with
Spotify: it does not reimplement a music player, it drives one that exists.
`analyze_code` stays on Nemotron directly (a new focused prompt,
`diagnose_code` - same shape as `summarize_for_speech`/`describe_image`):
explaining a bug in a few sentences is a reasonable single-completion task
in a way rewriting the function correctly is not.

**Undo is the safety net here too, not a confirmation gate** - a new
`undo.code_fixed(path, original_content)`, pushed only once the file is
confirmed to have actually changed. Unlike a delete, there is no recycle bin
for a code edit, so the entire original content is captured up front and
restored outright on "annule", rather than reasoning about a diff
afterwards. Verified end to end through the real "annule" path, not just
the undo entry in isolation.

**What is honestly unverified**: there is no `claude` binary in this
project's own dev sandbox (`claude --version` here reports "command not
found"), so the exact invocation - `--permission-mode acceptEdits`,
deliberately the narrower choice over `--dangerously-skip-permissions` so
file edits are auto-approved without also silently auto-approving arbitrary
shell commands - is Claude Code's documented headless behaviour as best
known when this was written, not something run and observed from here.
`is_available()`'s PATH check is real; `run()`'s exact flags may need
adjusting against `claude --help` on whichever machine this actually runs
on. A hard `AGENT_TIMEOUT_SECONDS` (5 minutes, a guess, not a measured
figure) exists specifically because this is the one action that blocks the
turn-handling thread for longer than a moment - a stuck or slow agent
degrades to an honest "ca prend trop de temps" rather than leaving Hey Peer
unresponsive with no way to tell.

**Review, not blind trust**: a successful fix opens VS Code's diff view
(`code --diff <backup> <file>`) comparing the original content against the
result, via a small new `open_diff_in_vscode` - `apps.launch()` has no way
to pass `--diff`'s two paths, so this goes straight to a resolved `code`
executable instead. Best-effort: VS Code not being on PATH does not fail the
turn, since the fix (and its undo entry) already happened either way, only
the review convenience is missing.

**A fourth and fifth instance of the "prompt says both yes and no" bug,
found live before shipping, not assumed fixed by adding the actions.**
"qu'est-ce qu'il y a sur mon ecran ?" (round 36's own new action) answered
"reply" with an *invented* screen description, because round 25's "you
cannot see... the screen" was still there, written before `read_screen`
existed. And "edit what is inside a file... writing into one is not" directly contradicted the `fix_code` this exact round was
adding. Both fixed in the same sections rounds 31/32/36 already had to
rewrite for the identical reason - restructured so screen questions route to
`read_screen`, and the refusal list stopped naming file-editing as
categorically impossible (code is different, prose/data inside a document
still is not). Verified live afterward across every action type shipped
this session, not just the two that had just broken - nothing else
regressed.

**One residual, measured rather than assumed away**: "analyse calc.py"
produced the literal action name `"analyse_code"` (French-influenced
spelling) instead of the real `"analyze_code"` in one single-sample check -
a hallucinated action name that would silently fall through to "je n'ai pas
compris" rather than dispatching. Re-measured at 10 repeats of the same
phrase: 10/10 correct. Noted as a low-frequency, general risk shared by
every action (any could in principle be misspelled the same way, this is
not specific to this one), not something this round adds defensive matching
for - the existing fallback already degrades to a safe "did not understand"
rather than a wrong action, and building fuzzy action-name matching for a
failure mode measured at roughly 1-in-10-or-rarer is exactly the kind of
speculative hardening this project's own established discipline (rounds
31/34/35) argues against chasing.

449 tests.

## Environment notes (this sandbox)

No microphone, no display server actually attached, no GPU, no Nebius API key here.
Code is written to be correct and unit-testable with mocks; anything needing real
hardware/API access is flagged and left runnable-but-unverified-here.
