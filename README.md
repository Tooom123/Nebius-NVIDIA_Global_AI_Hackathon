# Hey Peer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Hey Peer** is an always-listening personal assistant that observes a user's repeated
digital habits (sequences of actions across apps), detects patterns, and offers to
automate them on demand — activated by the voice keyword **"Hey Peer"**.

Built for the **Nebius x NVIDIA Global AI Hackathon** (track: *Personal AI*).

## What it does

1. A lightweight, fully local wake-word detector listens for "Hey Peer" (nothing is
   sent to the cloud before activation — privacy by design).
2. A pattern-detection module watches for repeated action sequences (e.g. filling the
   same form, renaming/sorting the same files) and stores them as reusable "skills".
3. Once activated, the user's spoken instruction plus a screenshot of the current
   screen are sent to **Nemotron 3 Nano Omni**, hosted on **Nebius Token Factory**,
   which reasons over audio + vision + text to produce a structured intent
   (`{action, skill_id, n_repetitions, ...}`).
4. The user is shown exactly what will be done and must explicitly confirm before
   anything executes.
5. Once confirmed, the matched skill is replayed — via direct filesystem operations
   for file-organizing skills, or mouse/keyboard automation with a visual check
   between steps for anything else.

## Why

Repetitive multi-app busywork (data entry, file sorting, form submission) is common
and tedious. Hey Peer learns these patterns passively and lets the user delegate them
with a single voice command, without ever acting without explicit confirmation.

## Demo scenario: file sorting

The concrete scenario this build targets: the user moves a few files (e.g. PDFs) out
of a watched folder (`~/Downloads` by default) into another folder a few times. Hey
Peer notices the repeated pattern — same source folder, same file extension, same
destination — and learns it as a skill. Saying "Hey Peer, do 4 more" replays it by
moving the next 4 matching files straight through the filesystem (`shutil.move`), not
by simulating clicks — so it's robust to the file manager window being anywhere on
screen, or not even open.

## Architecture

```
[Continuous capture]  →  [Pattern detection + skill memory]
        │                              │
        │ (wake word "Hey Peer")       │
        ▼                              │
[Interpretation — Nemotron 3 Nano Omni]◄──── (queries skill memory)
   (Nebius Token Factory · audio + screen)
        │
        ▼
[User confirmation]
        │
        ▼
[Execution — mouse/keyboard control]
        │
        └──► updates skill memory
```

See [CONTEXT.md](CONTEXT.md) for the full project rationale and design notes.

## Project layout

```
heypeer/
├── wakeword/       # openWakeWord training pipeline (Piper samples, augmentation,
│                   # training) + real-time ONNX-based listener
├── capture/        # active app/window watcher, abstracted input-event listener,
│                   # and a watchdog-based file-move watcher (demo scenario)
├── patterns/       # repeated-sequence detector + JSON-backed skill memory
├── nemotron/       # Nebius Token Factory client for Nemotron 3 Nano Omni
├── confirmation/   # user confirmation gate (CLI)
├── executor/       # automated replay: pyautogui for input skills, direct
│                   # filesystem ops (shutil) for file-move skills
├── main.py         # wires every stage into the end-to-end demo loop
└── config.py       # shared configuration (env vars, paths, model ids)
```

## Requirements

- Python 3.10+
- A [Nebius AI Studio / Token Factory](https://studio.nebius.ai/) API key with access
  to `nvidia/Nemotron-3-Nano-Omni` (verify the exact id in the platform's model
  catalog — casing has changed before)
- A microphone and display (for the wake-word listener and skill replay,
  respectively) — not required to run the test suite

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in NEBIUS_API_KEY
```

## Running

```bash
python -m heypeer.main
```

This starts the activity watcher and the file-move watcher (default: `~/Downloads`,
override with `HEYPEER_WATCHED_DIR`), learning skills from repeated action sequences
or repeated file moves. It then listens for "Hey Peer". If no trained wake-word model
exists yet at `data/wakeword/hey_peer.onnx`, it falls back to manual activation: press
Enter to simulate the wake word and type the instruction you'd otherwise speak.

To train the real wake-word model:

```bash
python -m heypeer.wakeword.generate_samples --voices <piper-voice.onnx> ...
python -m heypeer.wakeword.augment
python -m heypeer.wakeword.train --positive-dir ... --negative-dir ...
```

See each script's docstring for details.

## Status

Built incrementally during the hackathon, one commit per stage — see
[TODO.md](TODO.md) for the detailed build log and what's still open.

All core stages are implemented and unit-tested (`pytest`, 21 tests): wake-word
training/inference, activity capture, file-move capture/detection/replay for the
demo scenario, pattern detection, the Nemotron client, user confirmation, and skill
execution. What's *not* verified is anything needing real hardware this dev
environment didn't have — a microphone, a display, real Piper voices, or a live
Nebius API key — so those paths are code-complete but only verified via mocks.
Concretely: `WakeWordListener.start()`'s live mic loop, `ActivityWatcher.start()`'s
live input loop, `SkillRunner`'s pyautogui-based replay path (the file-move replay
path *is* verified — it only touches the filesystem), and any real (non-mocked)
Nebius API round-trip.

## Ethics & privacy notes

- The wake-word detector runs **entirely locally**; no audio leaves the machine
  unless "Hey Peer" is detected.
- Captured input events carry only what's needed to detect and replay a pattern
  (event type, app/window, click coordinates, special key names like Enter/Tab,
  scroll deltas) — never the literal characters typed into a field. Plain
  character key presses are recorded as a generic marker and the executor
  refuses to replay them, so no automation can ever retype captured content.
- **No automation ever runs without explicit user confirmation** of what will be done
  and how many times.

## License

MIT — see [LICENSE](LICENSE).
