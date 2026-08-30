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

## Environment notes (this sandbox)

No microphone, no display server actually attached, no GPU, no Nebius API key here.
Code is written to be correct and unit-testable with mocks; anything needing real
hardware/API access is flagged and left runnable-but-unverified-here.
