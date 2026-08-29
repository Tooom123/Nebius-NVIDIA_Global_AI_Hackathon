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
