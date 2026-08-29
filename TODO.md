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

### Requested next: real voice command + a real UI

The user was explicit that wake-word detection alone doesn't make sense
without also being able to *speak* the instruction — right now
`_default_get_instruction()` still requires typing after "Hey Peer" fires.
Also asked for a proper UI, sketched out concretely this time (not just "a
real UI" — an actual interaction design):

- [ ] **Voice command capture + interpretation** — record a few seconds of
      audio right after wake-word detection and route it through
      `NemotronClient.interpret()` (already built, accepts an audio clip +
      screenshot + skill context — never actually exercised end-to-end,
      only `interpret_text()` has been) instead of `input()`. Natural fit
      given Nemotron 3 Nano Omni is multimodal audio+vision+text already —
      no separate STT engine needed in principle. Needs: a short recording
      window (VAD-based end-of-speech detection, or a fixed few seconds),
      saving it as a wav, and wiring `HeyPeer._handle_instruction` to accept
      an audio path instead of/alongside text.
- [ ] **Corner popup UI on wake-word detection** — a modern light-mode
      floating window appears in a screen corner the moment "Hey Peer"
      fires, live-transcribing what's said (like OS dictation UI), closing
      once the instruction is captured. Needs a design pass: candidates are
      a lightweight always-on-top Tk/PyQt window, or a small local web view.
      Should reuse/replace the existing "Demander à Hey Peer..." tkinter
      dialog rather than duplicate it — that one is manual-trigger-only
      today, this one is wake-word-triggered.
- [ ] **Spoken confirmation (TTS)** — instead of (or alongside) the current
      text confirmation prompt, Hey Peer should *say* what it's about to do
      and wait for a spoken/typed yes before acting. Needs a TTS engine —
      Piper is already a project dependency (used for wake-word training
      data) and can also do live synthesis, worth trying first before adding
      another dependency.
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

## Environment notes (this sandbox)

No microphone, no display server actually attached, no GPU, no Nebius API key here.
Code is written to be correct and unit-testable with mocks; anything needing real
hardware/API access is flagged and left runnable-but-unverified-here.
