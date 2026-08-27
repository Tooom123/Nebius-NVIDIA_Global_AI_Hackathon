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
        tested with a mocked OpenAI client (no real API key in this sandbox)
  - [x] Extend to audio clip + screenshot (omni input) — `interpret()` sends
        base64 audio + screenshot; unverified against the live API here
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
  - [ ] Pick the actual concrete demo scenario (which app/task) — needs a
        real machine with display + mic to choose and rehearse; not doable in
        this sandbox
  - [ ] Wire real audio capture + screenshotting for `on_wake_word` (currently
        takes typed text as an instruction stand-in, per the plan's
        "text first" validation step) and swap in `NemotronClient.interpret`
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
