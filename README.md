# Hey Peer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Hey Peer** is an always-listening personal assistant that observes a user's repeated
digital habits (sequences of actions across apps), detects patterns, and offers to
automate them on demand — activated by the voice keyword **"Hey Peer"**.

Built for the **Nebius x NVIDIA Global AI Hackathon** (track: *Personal AI*).

## What it does

1. Hey Peer runs as a background app with a **system tray icon**. Skill-learning
   capture starts natively the moment it launches — it's passive observation, and
   nothing it does ever executes anything on its own (see step 5), so there's no
   real "off" state worth having for it.
2. A pattern-detection module watches for repeated action sequences (e.g. filling the
   same form, renaming/sorting the same files) and stores them as reusable "skills".
3. **"Mode auto (écoute vocale)"** is a separate tray toggle for something narrower:
   whether Hey Peer is actually listening for the wake word and able to act on it. It's
   a simple ON/OFF switch, **on by default** as soon as the app starts — turn it off
   from the tray menu if you don't want voice activation for that session. When it's
   on, a lightweight, fully local wake-word detector listens for "Hey Peer"
   (nothing is sent to the cloud before activation — privacy by design), and the
   **mouse cursor changes color** as a visible "Hey Peer can hear you" indicator
   (Windows only for now — see Status below).
4. Once activated, the user's spoken instruction plus a screenshot of the current
   screen are sent to **Nemotron 3 Nano Omni**, hosted on **Nebius Token Factory**,
   which reasons over audio + vision + text to produce a structured intent.
   Nemotron picks one of: replay a learned skill, or a **direct one-off file
   action** that doesn't need any learned skill at all — move, rename, create, or
   delete a specific file/folder (e.g. "déplace le fichier facture vers Archives",
   "renomme facture.pdf en facture_mars.pdf", "crée un dossier Factures",
   "supprime notes.txt" — all grounded against the watched folder's actual file
   listing) — or reports the instruction as unrecognized.
5. Hey Peer narrates what it's about to do out loud (in French by default) and then
   does it — **no confirmation prompt** stands in the way any more. There used to be
   one (spoken or typed); it was removed after real-world testing showed it caused
   more problems than it solved (a misheard "yes" over a noisy mic would silently
   default to "no" and block a legitimate action). The safety net that replaces it:
   deletes go to the recycle bin/trash rather than a permanent unlink, and every file
   operation is confined to the watched directory (see Ethics & privacy notes below).
6. It's carried out — via direct filesystem operations for file-organizing skills
   and file actions, or mouse/keyboard automation with a visual check between steps
   for anything else. The tray icon turns blue while something is running, so the
   current status is always visible from the hidden-icons area.

For quick testing or debugging without a mic, the tray menu also has a **"Demander
à Hey Peer..."** item that opens a small text-input dialog and feeds it through the
exact same interpretation → execution path as a real wake-word activation.

## Why

Repetitive multi-app busywork (data entry, file sorting, form submission) is common
and tedious. Hey Peer learns these patterns passively and lets the user delegate them
with a single voice command.

## Demo scenario: file sorting

The concrete scenario this build targets: the user moves a few files (e.g. PDFs) out
of a watched folder (`~/Downloads` by default) into another folder a few times. Hey
Peer notices the repeated pattern — same source folder, same file extension, same
destination — and learns it as a skill. Saying "Hey Peer, do 4 more" replays it by
moving the next 4 matching files straight through the filesystem (`shutil.move`), not
by simulating clicks — so it's robust to the file manager window being anywhere on
screen, or not even open.

Alongside that, Hey Peer can also handle a **single named file or folder directly**,
with no repetition and no learned skill involved at all — move, rename, create, or
delete ("déplace le fichier facture vers Archives", "renomme facture.pdf en
facture_mars.pdf", "crée un dossier Factures", "supprime notes.txt") — pure Nemotron
reasoning grounded against the real filenames in the watched folder. As a safety
constraint, every one of these resolves to a path *inside the watched directory*
(checked, not just assumed — see Ethics & privacy notes), so a misunderstood or
ambiguous instruction can't write, rename, or delete outside it.

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
[Execution — filesystem ops / mouse+keyboard control]
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
├── executor/       # automated replay: pyautogui for input skills, direct
│                   # filesystem ops (move/rename/create/delete) for file actions
├── tray/           # system tray icon (voice-activation toggle, live status,
│                   # manual prompt dialog) + colored-cursor indicator
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
entry. Capture (learning repeated action sequences and repeated file moves —
default watched folder `~/Downloads`, override with `HEYPEER_WATCHED_DIR`) starts
immediately and runs natively the whole time the app is open; the tray icon's color
and tooltip/menu text always show voice-listening status (off / listening /
executing). **"Mode auto (écoute vocale)"** starts ON by default — toggle it off
from the tray menu if you don't want voice activation for that session. A trained
wake-word model ships at `data/wakeword/hey_peer.onnx` — if it's missing, voice
activation just won't come up regardless of the toggle; use the tray's **"Demander
à Hey Peer..."** item to type an instruction instead.

While the wake word is being validated on real hardware, a temporary debug mode is
on by default: a live mic dB meter and detection score print to the console, and
the input device name prints at startup — set `HEYPEER_WAKEWORD_DEBUG=0` once it's
reliably working to quiet this. The detection threshold defaults to `0.9` (not
openWakeWord's usual `0.5`) — see `heypeer/wakeword/train.py`'s module docstring
for the evaluation behind that choice — override with `HEYPEER_WAKEWORD_THRESHOLD`.

For debugging with the console visible (or on a headless box without a tray
host), use the foreground console loop instead:

```bash
python -m heypeer.main --cli
```

This always runs with capture and voice activation both on, falls back to
pressing Enter to simulate the wake word if no trained model is available, and
still shows a real (detached) tray icon so "Quitter" works as a stop button
instead of Task Manager. **The actual conversation (wake word detected, instruction
heard, resolved intent, result) is logged to the terminal** — both modes also show
a minimal always-on-top visual indicator (`heypeer/tray/debug_window.py`): a small
white circle with an Apple-style colored accent, sitting flush against the top edge
of the screen, with animated wave rings radiating outward while listening/thinking/
speaking (rendered via `pywebview` — the OS's own web view, WebView2 on Windows —
loading `heypeer/tray/webui/conversation.html`). It runs in its own OS process (not
just a thread) specifically so that if window creation ever hangs or fails on some
machine, the rest of Hey Peer keeps running unaffected instead of the whole app
freezing with it.

Hey Peer's own TTS output is muted out of its own wake-word listening while it's
speaking (`WakeWordListener.mute()`/`unmute()`, wired around every `_speak()` call in
`main.py`) — with some headsets, its own voice was otherwise picked back up by the
mic and could be scored as more speech or even a false wake-word trigger. This is
mic *gating*, not true acoustic echo cancellation (nothing is cancelled during
simultaneous playback+speech) — but Hey Peer never needs to listen for the wake word
while it's actively talking anyway, so gating fully covers the symptom.

To regenerate the wake-word model (voices aren't committed — download them first):

```bash
python -c "from piper import download_voices as d; from pathlib import Path; \
  d.download_voice('en_US-lessac-medium', Path('data/wakeword/piper_voices'))"
# repeat for en_US-amy-medium, en_US-ryan-medium (or other voices)

python -m heypeer.wakeword.generate_samples --voices data/wakeword/piper_voices/*.onnx
python -m heypeer.wakeword.generate_negatives --voices data/wakeword/piper_voices/*.onnx
python -m heypeer.wakeword.augment
python -m heypeer.wakeword.train --positive-dir ... --negative-dir ...
```

See each script's docstring for details, and TODO.md for what the current model
was actually trained/evaluated on (including a voice-leakage bug found and
worked around — don't reintroduce a single voice used in both positive and
negative sets without checking for this).

## Status

Built incrementally during the hackathon, one commit per stage — see
[TODO.md](TODO.md) for the detailed build log and what's still open.

All core stages are implemented and unit-tested (`pytest`, 100 tests): wake-word
training/inference, activity capture, file-move capture/detection/replay for the
demo scenario, pattern detection, the Nemotron client (**verified against the live
Nebius API**, not just mocks), direct file actions (move/rename/create/delete) with
path-containment safety checks, skill execution, and the tray app/cursor indicator.
Two full pipelines have been rehearsed end-to-end with real files and real API
calls: learn a file-sorting skill -> "Hey Peer, do N more" -> real file move; and a
direct one-off "déplace le fichier X vers Y" with no learned skill at all.

The wake-word model has moved from "never trained" to **actually trained on real
Piper-synthesized speech**, with a proper (if synthetic-only) held-out streaming
evaluation — 100% recall / ~6.9% false-accept rate at the shipped 0.9 threshold. Two
real training bugs were caught by that evaluation (not by held-out clip accuracy
alone, which looked fine and hid both): missing alignment augmentation, and a
single voice used in both classes leaking through as a shortcut. See TODO.md for
the full story — and the model still hasn't been tested against a real human voice.

The tray app + cursor indicator have been smoke-tested on a real Windows machine
across three rounds, surfacing (and fixing) several real bugs — see TODO.md for the
full writeup of each:
- `ActivityWatcher`/`FileOpWatcher` sharing one pattern detector (mouse noise
  during a drag-and-drop could eat the real file-move pattern)
- The hand-drawn cursor shape looking wrong (now recolors Windows' own arrow
  bitmap instead of approximating one)
- The cursor never being reset on quit
- A `ctypes.ArgumentError: int too long to convert` crash from undeclared win32
  `argtypes`/`restype` truncating 64-bit handles
- The prompt dialog coming up broken (`grab failed`, unresponsive) because it was
  created from inside pystray's native message-dispatch callback instead of its
  own thread
- The confusing "Mode auto" semantics that gated capture, voice, and the cursor
  together — capture is now native/always-on, the toggle is voice-only (and now
  starts ON by default)
- An `OSError: Unexpected color cursor for IDC_ARROW` crash — the extraction code
  only handled the classic monochrome cursor and hard-failed on the 32bpp color
  cursor this user's actual Windows theme uses; both are now supported

What's still *not* verified is anything needing real hardware/OS features this dev
environment doesn't have:
- `WakeWordListener.start()`'s live mic loop against a **real human voice** —
  everything so far is synthetic-Piper-voice evaluation
- The tray "Demander à Hey Peer..." dialog's actual on-screen appearance (fixed
  the threading bug behind it, but haven't seen it render for real)
- The pywebview orb indicator's actual rendered appearance — this sandbox has
  no GTK/WebKit backend for pywebview to use at all, so unlike most of this
  project's GUI code, even non-visual construction couldn't be exercised here
  for real (only through mocks); needs a real run on the user's Windows machine
- The recolored-arrow cursor's actual on-screen shape/color — verified logically
  for both the monochrome and color-cursor extraction paths, not yet seen render
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
- **There is no confirmation prompt before an action runs** — removed after
  real-world testing showed it caused more problems than it solved. In its place:
  every direct file action (move/rename/create/delete) is checked to resolve to a
  path *inside the watched directory* before touching the filesystem
  (`_ensure_within` in `heypeer/executor/runner.py`) — a hallucinated or ambiguous
  name can't escape it via `../` or an absolute path — and deletes go to the
  recycle bin/trash (`send2trash`), not a permanent unlink, so at least that
  action stays reversible.

## License

MIT — see [LICENSE](LICENSE).
