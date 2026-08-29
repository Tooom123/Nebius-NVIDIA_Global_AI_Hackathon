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
