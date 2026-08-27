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
- [ ] Automated execution
  - [ ] `SkillRunner.run` replay via pyautogui
  - [ ] Visual verification hook between steps (screenshot → Nemotron check)
- [ ] Demo scenario
  - [ ] Pick and script the single demonstrable scenario end-to-end
  - [ ] Wire `heypeer/main.py` into a runnable demo loop
- [ ] Submission polish
  - [ ] README install/run instructions kept accurate as pieces land
  - [ ] Ethics/privacy section accurate
  - [ ] 3-min demo video (outside coding scope — flag as manual follow-up)

## Environment notes (this sandbox)

No microphone, no display server actually attached, no GPU, no Nebius API key here.
Code is written to be correct and unit-testable with mocks; anything needing real
hardware/API access is flagged and left runnable-but-unverified-here.
