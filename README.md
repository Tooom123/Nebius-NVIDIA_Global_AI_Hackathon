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
5. Once confirmed, the matched skill is replayed via mouse/keyboard automation, with a
   lightweight visual check between steps to catch UI drift.

## Why

Repetitive multi-app busywork (data entry, file sorting, form submission) is common
and tedious. Hey Peer learns these patterns passively and lets the user delegate them
with a single voice command, without ever acting without explicit confirmation.

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
├── wakeword/       # openWakeWord model, training pipeline, real-time listener
├── capture/        # lightweight activity capture (active app/window, action events)
├── patterns/       # repeated-sequence detection + skill memory (JSON/SQLite)
├── nemotron/        # Nebius Token Factory client for Nemotron 3 Nano Omni
├── confirmation/   # user confirmation UI (CLI/overlay)
├── executor/       # automated replay of skills via pyautogui + visual checks
└── config.py       # shared configuration (env vars, paths, model ids)
```

## Requirements

- Python 3.10+
- A [Nebius AI Studio / Token Factory](https://studio.nebius.ai/) API key with access
  to `nvidia/nemotron-3-nano-omni` (or the current model id on the platform)

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

(See individual module docstrings under `heypeer/` for how to run each stage —
wake-word training, pattern detection, and the demo loop — independently.)

## Ethics & privacy notes

- The wake-word detector runs **entirely locally**; no audio leaves the machine
  unless "Hey Peer" is detected.
- Only abstracted action events (app/window focus, input event types) are captured,
  never keystroke content.
- **No automation ever runs without explicit user confirmation** of what will be done
  and how many times.

## License

MIT — see [LICENSE](LICENSE).
