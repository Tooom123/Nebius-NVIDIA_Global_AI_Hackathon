# Hey Peer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Hey Peer** is an always-listening personal assistant that observes a user's repeated
digital habits (sequences of actions across apps), detects patterns, and offers to
automate them on demand — activated by the voice keyword **"Hey Peer"**.

Built for the **Nebius x NVIDIA Global AI Hackathon** (track: *Personal AI*).

## What it does

1. Hey Peer runs as a background app with a **system tray icon**. A "Mode auto"
   toggle in its menu arms/disarms everything else — nothing runs, and no cursor
   changes, unless auto mode is on.
2. When armed, a lightweight, fully local wake-word detector listens for "Hey Peer"
   (nothing is sent to the cloud before activation — privacy by design), and the
   **mouse cursor changes color** as a visible "Hey Peer is watching" indicator
   (Windows only for now — see Status below).
3. A pattern-detection module watches for repeated action sequences (e.g. filling the
   same form, renaming/sorting the same files) and stores them as reusable "skills".
4. Once activated, the user's spoken instruction plus a screenshot of the current
   screen are sent to **Nemotron 3 Nano Omni**, hosted on **Nebius Token Factory**,
   which reasons over audio + vision + text to produce a structured intent.
   Nemotron picks one of: replay a learned skill, do a **direct one-off action**
   that doesn't need any learned skill at all (e.g. "déplace le fichier facture
   vers Archives" — grounded against the watched folder's actual file listing), or
   report the instruction as unrecognized.
5. The user is shown exactly what will be done and must explicitly confirm before
   anything executes — no exception for direct actions either.
6. Once confirmed, it's carried out — via direct filesystem operations for
   file-organizing skills and direct file moves, or mouse/keyboard automation with a
   visual check between steps for anything else. The tray icon turns blue while
   something is running, so the current status is always visible from the
   hidden-icons area.

For quick testing or debugging without a mic, the tray menu also has a **"Demander
à Hey Peer..."** item that opens a small text-input dialog and feeds it through the
exact same interpretation → confirmation → execution path as a real wake-word
activation.

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

Alongside that, Hey Peer can also handle a **single named file directly**, with no
repetition and no learned skill involved at all ("déplace le fichier facture vers
Archives") — pure Nemotron reasoning grounded against the real filenames in the
watched folder. As a safety constraint, the destination is always resolved as a
subfolder *of the watched directory* (created if it doesn't exist), so a
misunderstood or ambiguous instruction can't write outside it — and it still goes
through the same confirmation gate as everything else.

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
├── tray/           # system tray icon (auto-mode toggle, live status) +
│                   # colored-cursor indicator for when auto mode is armed
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

This starts Hey Peer as a **background app with a system tray / hidden-icons**
entry. Nothing is captured and no cursor changes until you turn on **"Mode auto"**
from the tray menu — the tray icon also always shows current status (paused /
listening / executing) as both its color and its tooltip/menu text. Once armed, it
watches for repeated action sequences and repeated file moves (default watched
folder: `~/Downloads`, override with `HEYPEER_WATCHED_DIR`), and listens for "Hey
Peer". If no trained wake-word model exists yet at `data/wakeword/hey_peer.onnx`,
voice activation is unavailable for that session but file-move detection still
works.

For a headless dev box without a tray host (no display), use the foreground
console loop instead:

```bash
python -m heypeer.main --cli
```

This always runs with auto mode on and falls back to pressing Enter to simulate
the wake word if no trained model is available.

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

All core stages are implemented and unit-tested (`pytest`, 43+ tests): wake-word
training/inference, activity capture, file-move capture/detection/replay for the
demo scenario, pattern detection, the Nemotron client (**verified against the live
Nebius API**, not just mocks), user confirmation, skill execution, and the tray
app/cursor indicator. Two full pipelines have been rehearsed end-to-end with real
files and real API calls: learn a file-sorting skill -> "Hey Peer, do N more" ->
confirm -> real file move; and a direct one-off "déplace le fichier X vers Y" with
no learned skill at all.

The tray app + cursor indicator have now been smoke-tested on a real Windows
machine, which surfaced (and fixed) three real bugs: `ActivityWatcher` and
`FileOpWatcher` were sharing one pattern detector, so mouse noise during a
drag-and-drop could produce a bogus click-based "skill" that silently ate the real
file-move pattern; the hand-drawn cursor shape looked wrong (now recolors Windows'
actual arrow bitmap instead of drawing an approximation); and quitting via the tray
menu never actually reset the cursor. See TODO.md for the full writeup.

What's still *not* verified is anything needing real hardware/OS features this dev
environment doesn't have:
- `WakeWordListener.start()`'s live mic loop
- The tray "Demander à Hey Peer..." dialog's actual on-screen appearance
- **Ctrl+C does not reliably stop the tray app on Windows** — this is a pystray/
  Win32 message-loop limitation, not a bug to fix; use the tray menu's "Quitter"
  instead, which also resets the cursor
- There is still **no cursor-color support at all on macOS/Linux** —
  `set_active()` there just logs and no-ops

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
