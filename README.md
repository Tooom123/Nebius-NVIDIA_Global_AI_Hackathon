# Hey Peer

[![tests](https://github.com/Tooom123/Nebius-NVIDIA_Global_AI_Hackathon/actions/workflows/tests.yml/badge.svg)](https://github.com/Tooom123/Nebius-NVIDIA_Global_AI_Hackathon/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Say it. It's done.**

**Hey Peer** is an always-on voice assistant for Windows that *acts on your
machine* rather than telling you how to. No mouse, no keyboard: say "Hey
Peer", give an instruction - or several in one breath - and it takes the
controls. It moves files, opens and drives apps, fixes code and pushes it,
answers mail, builds a Spotify playlist and shares it on WhatsApp, puts
sound effects on a CapCut timeline, runs your routines - in French or
English, switching sentence by sentence.

The wake word, speech recognition and speech synthesis all run **locally**:
your voice never leaves your machine. Only text reaches the model.

Built by Tom Angles (Paris) for the **Nebius x NVIDIA Global AI Hackathon**,
track *Personal AI*, on **NVIDIA Nemotron** via **Nebius Token Factory**.

## Why

A working day is spread across a dozen apps, and every one of them wants
your clicks. Assistants that *answer* questions still leave you doing the
work. Hey Peer is the other half: you say what you want done, and it does
it on your own computer, with your own apps and accounts, while you keep
your hands - and your voice data - to yourself.

## How it uses Nebius Token Factory and NVIDIA Nemotron

| Job | Model | Where |
|---|---|---|
| Understanding every turn: which action, with what arguments, or a spoken answer, or a question back | **NVIDIA Nemotron** - `nvidia/Nemotron-3_5-Lightning` | Nebius Token Factory |
| Splitting one long instruction into ordered steps (`"action": "multi"`) | Nemotron | Nebius Token Factory |
| Diagnosing code, writing the cue sheet for CapCut sound effects, summarising documents and screens for speech | Nemotron | Nebius Token Factory |
| Anything that needs eyes: reading the screen, describing video frames | `google/gemma-3-27b-it` | Nebius Token Factory |
| Open-ended browser tasks (mail, research) | [Hermes Agent](https://hermes-agent.nousresearch.com/), provider `nebius-token-factory` by default | Nebius Token Factory |

Token Factory's OpenAI-compatible API means the client is the `openai` SDK
pointed at Nebius's base URL (`heypeer/nemotron/client.py`). Every turn is
grounded with real context - the actual file names in the folder you're
working in, the facts you asked Hey Peer to remember, the names of your
routines - so Nemotron resolves "move the invoice to Archives" to a real
`facture_mars.pdf`, never an invented path.

## Architecture

```
 ON YOUR PC - PRIVATE                       NEBIUS TOKEN FACTORY
 ─────────────────────                      ────────────────────
 Wake word  (openWakeWord, your voice)
      │
 Speech to text (faster-whisper + Silero VAD)
      │  text ─────────────────────────────►  NVIDIA Nemotron
      │                                       (+ Gemma 3 27B for vision)
      │  ◄──────────────── structured action ─┘
      ▼
 The hands
   • File actions (safe zones, undo, recycle bin)
   • Desktop apps (Windows UI Automation)
   • Coding agent (Claude Code, headless)
   • Hermes Agent driving your own Chrome
   • Spotify & WhatsApp Web (fixed steps over Chrome DevTools)
   • CapCut, FL Studio, volume, brightness, windows, timers...
      │
 Spoken reply (Piper for French, Kokoro for English)
```

## What it can do

- **Files** - move, rename, create, delete ("déplace la facture vers
  Archives"). Every path must resolve inside a *safe zone* (your own files,
  never `C:\Windows`, `Program Files` or `~/.ssh`); deletes go to the recycle
  bin; say **"undo"** / **"annule"** to roll the last action back.
- **Apps and the desktop** - open apps from a known registry, maximise,
  minimise, close, show the desktop, volume, brightness, clipboard, and
  **click any named control** ("click Send") through Windows UI Automation,
  with a visible pointer flying to it.
- **Code** - "why does this function crash?", "fix it", "commit and push":
  Nemotron diagnoses, a real coding agent (Claude Code, headless) edits, and
  the change is committed and pushed.
- **Browser tasks** - mail, research and other open-ended work are handed to
  Hermes Agent, which drives a dedicated Chrome profile signed in to your
  accounts.
- **Music and messages** - plays a track ("play Alright by Kendrick Lamar"),
  builds a Spotify playlist and sends its link to a contact on WhatsApp Web.
- **Creative tools** - lays a drum pattern into FL Studio; watches a CapCut
  video, picks sounds from your own folder and places them on the timeline.
- **Screen and documents** - "what's on my screen?", "summarise this PDF",
  "what is she saying in this video?" (system audio, Windows).
- **Conversation** - ordinary questions get spoken answers; a missing detail
  gets a question back ("Which folder?") and the microphone stays open for
  the reply, no wake word needed.

## Personal AI

- **Always on** - a tray app, optionally started at login, listening only
  for its wake word, locally.
- **Private** - audio is processed on your PC; your memory, routines and
  wake-word model are local files.
- **Persistent memory** - "remember that I prefer to be called Tom" is
  stored in a local `memory.json` and given to Nemotron on every turn.
- **Reusable skills** - named routines ("when I say *good morning*, open
  Spotify and read my timers"), and after the same request three times Hey
  Peer offers to turn it into one.
- **Safe by design** - safe zones, recycle bin, undo, and an app registry
  instead of running whatever a model returned.

## Project layout

```
heypeer/
├── wakeword/       # openWakeWord training pipeline + real-time listener,
│                   # faster-whisper transcription, wake-word verification
├── nemotron/       # Nebius Token Factory client, intent schema, prompts
├── executor/       # the hands: files, apps, UI Automation, coding agent,
│                   # Hermes, browser, Spotify, WhatsApp, CapCut, FL Studio...
├── tray/           # tray app, the blob indicator, captions, TTS (Piper/Kokoro)
├── memory.py       # persistent facts
├── habits.py       # routine suggestions after repeated requests
├── startup.py      # opt-in launch at login
├── main.py         # wires every stage together
└── config.py       # shared configuration (env vars, paths, model ids)
motion/             # the closing motion design of the demo video (HyperFrames)
```

## Requirements

- Windows 10/11 for the full experience (the test suite runs anywhere)
- Python 3.10+
- A [Nebius Token Factory](https://studio.nebius.ai/) API key with access to
  two models (check the exact ids in the model catalog - casing has changed
  before, and models get retired):
  - `nvidia/Nemotron-3_5-Lightning` for interpreting turns (`NEMOTRON_MODEL_ID`)
  - `google/gemma-3-27b-it` for the calls that send an image (`VISION_MODEL_ID`)
- A microphone and speakers
- Optional, each degrading gracefully when absent: the `claude` CLI (coding
  agent), the `hermes` CLI (browser tasks), Google Chrome, the Spotify desktop
  app, `ffmpeg` and `pycapcut` (CapCut), FL Studio

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in NEBIUS_API_KEY
```

Two capabilities are opt-in extras rather than default installs.

**Clicking things on screen.** "Clique sur Envoyer" finds the control in the
window's accessibility tree, flies a pixel-art pointer to it and presses it.

```bash
pip install uiautomation    # Windows only
```

Without it Hey Peer says it cannot click and nothing else changes. The
pointer is red by default; set `HEYPEER_CURSOR_COLOR=r,g,b` to change it.

**A better English voice.** Hey Peer speaks French through Piper and English
through [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0),
whose English voices are graded A-/A against Piper's audibly synthetic ones.

```bash
pip install kokoro       # also needs the espeak-ng binary
```

Without it English falls back to Piper and nothing else changes. French
deliberately stays on Piper either way: Kokoro's single French voice is
trained on the same SIWIS corpus Piper already offers, so there is nothing
to gain and real latency to lose. Measured on CPU, warm: Kokoro English is
RTF 0.02, Kokoro French RTF 0.61. See `heypeer/tray/kokoro_tts.py`.

The other extra: listening
to what the computer is *playing* ("resume ce que dit cette video") needs
WASAPI loopback, which is Windows-only and ships in a separate package.

```bash
pip install pyaudiowpatch   # Windows only; everything else works without it
```

Without it Hey Peer says it cannot listen to system audio, and nothing else
changes. It is deliberately not in `requirements.txt`: the package has no
macOS or Linux wheel, so requiring it would break `pip install` for
everyone not on Windows.

## Building a standalone Windows executable

So a demo machine needs neither a git clone nor `pip install`:

```bash
pip install pyinstaller
pyinstaller heypeer.spec     # produces dist/HeyPeer.exe
```

The wake-word model and the Piper voices are deliberately **not** bundled.
The wake-word model is trained on your own voice, so shipping someone
else's would be worse than shipping none; the voices are large and
downloaded on first use. In a frozen build both live in
`%LOCALAPPDATA%\HeyPeer` rather than beside the executable — see
`heypeer/paths.py` for why user data and bundled resources resolve
differently.

## Starting automatically at login

```bash
python -m heypeer.startup enable    # or: disable, status
```

Creates a shortcut in your Startup folder (Windows only). A shortcut rather
than a registry key or a service, so you can find and delete it yourself in
`shell:startup` without regedit — and so it stays inside your desktop
session, where the tray icon, the overlay and the microphone live.

## Previewing the indicator without running the app

Iterating on the blob used to mean launching Hey Peer on a real Windows
machine and saying the wake word to see two seconds of animation. This
renders the same frames straight to a video file:

```bash
python -m heypeer.tray.blob_preview --state speaking --seconds 3
python -m heypeer.tray.blob_preview --all-states      # one file per state
python -m heypeer.tray.blob_preview --state idle --level 0.0   # pin the mic level
```

MP4 when `ffmpeg` is on PATH, animated GIF otherwise. Every parameter comes
from the live indicator's own constants, so the preview cannot drift from
what the app actually draws.

## Running

```bash
python -m heypeer.main          # tray app
python -m heypeer.main --cli    # same, with the conversation logged to the console
```

Hey Peer starts in the system tray, listening for "Hey Peer". The blob
indicator slides down from the top of the screen while it listens, thinks
and speaks, then hides between turns. The tray menu's **"Demander à Hey
Peer..."** takes a typed instruction through exactly the same path, for a
machine without a microphone.

How a turn works:

- **Wake word, in two stages.** A small always-on ONNX detector proposes;
  the start of the faster-whisper transcript confirms that it really heard
  "Hey Peer" before anything is acted on. Threshold `0.9` by default
  (`HEYPEER_WAKEWORD_THRESHOLD`).
- **The end of your sentence is measured, not assumed** - relative to the
  room's own noise floor, with ~1.2 s of trailing silence, so a pause between
  a file name and a destination does not cut you off.
- **Hey Peer does not listen to itself.** The wake-word listener is muted for
  the whole turn, from detection to the end of the spoken reply.
- **No confirmation prompt.** It was removed after real-world testing: a
  misheard "yes" blocked more legitimate work than it prevented mistakes.
  Undo, the recycle bin and safe zones replace it.

Set `HEYPEER_WAKEWORD_DEBUG=1` for a live microphone meter and per-chunk
detection scores in the console.

### Personalising the wake word to your voice

The shipped model is trained on synthetic speech only, which is why it both
over-fires and occasionally misses. Recording ~40 samples of your own voice fixes
the cause rather than compensating for it:

```bash
python -m heypeer.wakeword.record_samples   # guided; ~5 minutes
python -m heypeer.wakeword.train            # picks up the standard sample dirs
python -m heypeer.wakeword.evaluate         # scores the new model on your voice
```

No paths needed — all three default to the conventional sample directories and
use whichever exist. (`--positive-dir`/`--negative-dir` are still there, and are
repeatable, if you keep samples somewhere else.)

The recorder asks for two sets, and the second matters as much as the first: the
wake word itself, and **the same voice saying other things** — near-misses ("Hey
Pierre"), the commands you actually give, and ordinary speech. With positives
only, the model can separate the classes on voice identity alone and will fire on
anything you say.

`evaluate` runs each clip through the recognizer the way the live listener does
(streaming, peak score) and prints recall against false-accept rate per
threshold, so you can pick `HEYPEER_WAKEWORD_THRESHOLD` from measurements. It
also names the clips holding the model back — the lowest-scoring positives
(usually a bad take worth deleting) and the highest-scoring negatives, with the
phrase each one was.

**Nothing personal is committed.** Your recordings
(`data/wakeword/samples/`) and your trained model
(`data/wakeword/hey_peer_user.onnx`) are both gitignored. Training writes to
that personal path, and the runtime prefers it over the generic
`hey_peer.onnx` that ships with the repository — so your model is picked up
automatically, a fresh clone still works without one, and neither can
overwrite the other.

To regenerate the synthetic part of the training set (voices aren't committed — download them first):

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

- **1000+ tests** (`pytest`), run on every push by GitHub Actions.
- The Nemotron client is verified against the **live Nebius endpoint**, not
  only mocks - two prompt-behaviour bugs were found that way and fixed.
- Every step of the demo video - FL Studio, mail, the code fix and push,
  the Spotify playlist sent on WhatsApp, CapCut sound effects - was run end
  to end on a real Windows machine.
- See [TODO.md](TODO.md) for the full build log, and [CONTEXT.md](CONTEXT.md)
  for the original rationale.

Known limits: Windows only for the full feature set (elsewhere the overlay
and the cursor degrade to no-ops); Ctrl+C does not reliably stop the tray app
on Windows - use the tray menu's "Quitter".

## Feedback on Nebius Token Factory and NVIDIA Nemotron

- **What worked well.** The OpenAI-compatible API made the integration a
  base URL and a key. Nemotron is fast enough for a voice loop and reliable
  at strict JSON output, which is what turns speech into actions.
- **Model lifecycle.** The project started on `nvidia/Nemotron-3-Nano-Omni`,
  which was removed from Serverless on 2026-08-31. Its replacement,
  `Nemotron-3_5-Lightning`, does not accept images, so vision moved to Gemma
  3 27B on the same platform. Earlier notice of retirements would help.
- **Audio input.** Every audio content-part shape we tried (`input_audio`,
  `audio_url`, `audio`) was rejected with a 422, so speech is transcribed
  locally and only text is sent - which turned out to be the better design
  for privacy anyway.
- **Images with JSON mode.** An image together with
  `response_format={"type": "json_object"}` returned a 400 on the earlier
  Nemotron deployment, while it works on Gemma 3 27B; image calls are
  therefore kept separate from the classifier call.
- **Model ids are case-sensitive**, and the catalog's casing has changed
  over time.

## Ethics & privacy notes

- The wake word, speech recognition and speech synthesis run **entirely
  locally**; no audio ever leaves the machine. What reaches Nebius Token
  Factory is the transcribed text, plus a screenshot or video frames only
  when you ask about your screen or a video.
- Memory, routines and your personal wake-word model are local files, and
  none of them is committed to git.
- Every file action is checked to resolve inside a safe zone before it
  touches the filesystem (`executor/safe_zones.py`, `_ensure_within` in
  `executor/runner.py`), so a hallucinated or ambiguous name cannot escape
  through `../` or an absolute path. Deletes go to the recycle bin
  (`send2trash`), never a permanent unlink.
- Apps are launched from a registry, never from whatever the model
  returned: everything on that path began as a speech transcript.
- Outward actions (pushing code, sending mail or messages) happen only when
  you ask for them.

## License

MIT - see [LICENSE](LICENSE).
