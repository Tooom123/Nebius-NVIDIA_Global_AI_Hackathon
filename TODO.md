# Hey Peer — build TODO

Working list for the hackathon build-out. Check off as each lands; commit + push after
each major implementation (per project convention).

- [x] Project scaffold: license, README, package skeleton, skill memory + test
- [ ] Wake word "Hey Peer"
  - [ ] Piper TTS sample-generation script (synthetic "Hey Peer" utterances)
  - [ ] openWakeWord training script (features + small CNN, ONNX export)
  - [ ] Real-time runtime listener (mic → openWakeWord → callback), with a
        pretrained fallback model so the runtime path works before custom
        training is run
- [ ] Activity capture (minimal, scoped to one demo scenario)
  - [ ] Cross-platform-ish active app/window watcher
  - [ ] Mouse/keyboard event listener emitting `ActionEvent`s (no keystroke content)
- [ ] Pattern detection + skill memory
  - [ ] Sliding-window repeated-sequence detector (implement `PatternDetector.observe`)
  - [ ] Wire detector output into `SkillMemory`
- [ ] Nemotron 3 Nano Omni via Nebius Token Factory
  - [ ] OpenAI-compatible client call (text-first, per plan step 4)
  - [ ] Extend to audio clip + screenshot (omni input) once text path is verified
  - [ ] Parse structured intent (`{action, skill_id, n_repetitions}`)
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
