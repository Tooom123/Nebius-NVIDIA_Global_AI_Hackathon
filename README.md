# Hey Peer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Hey Peer** is an always-listening personal assistant that observes a user's repeated
digital habits (sequences of actions across apps), detects patterns, and offers to
automate them on demand — activated by the voice keyword **"Hey Peer"**.

Built for the **Nebius x NVIDIA Global AI Hackathon** (track: *Personal AI*).

## What it does

1. Hey Peer runs as a background app with a **system tray icon**.
2. **Skill learning is currently off**, and Hey Peer is voice-to-action only. The
   machinery is still there — a pattern detector that spots repeated action
   sequences and stores them as replayable "skills" — but in practice the skills
   it learned never matched a spoken instruction while being sent to the model on
   every request, and the global input hooks that fed it cost real performance.
   Set `HEYPEER_LEARN_SKILLS=1` (and `HEYPEER_CAPTURE_INPUT=1` for mouse/keyboard
   habits) to turn it back on.
3. **"Mode auto (écoute vocale)"** is a separate tray toggle for something narrower:
   whether Hey Peer is actually listening for the wake word and able to act on it. It's
   a simple ON/OFF switch, **on by default** as soon as the app starts — turn it off
   from the tray menu if you don't want voice activation for that session. When it's
   on, a lightweight, fully local wake-word detector listens for "Hey Peer"
   (nothing is sent to the cloud before activation — privacy by design), and the
   **mouse cursor changes color** as a visible "Hey Peer can hear you" indicator
   (Windows only for now — see Status below).
4. Once activated, the user's transcribed instruction is sent to **Nemotron 3
   Nano Omni**, hosted on **Nebius Token Factory**, grounded against the watched
   folder's real file and folder listing, to produce a structured intent.
   Nemotron resolves it to a **direct one-off file action** — move, rename,
   create, or delete a specific file/folder (e.g. "déplace le fichier facture vers Archives",
   "renomme facture.pdf en facture_mars.pdf", "crée un dossier Factures",
   "supprime notes.txt" — all grounded against the watched folder's actual file
   listing) — or reports the instruction as unrecognized.
5. Hey Peer narrates what it's about to do out loud (in French by default) and then
   does it — **no confirmation prompt** stands in the way any more. Say **"annule"**
   to reverse the last action, and for a few seconds afterwards a follow-up command
   needs no wake word at all. If something is missing from an instruction, Hey Peer
   asks for exactly that ("Vers quel dossier ?") rather than saying it didn't
   understand. There used to be
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
│                   # manual prompt dialog), colored-cursor indicator, and the
│                   # layered-window blob overlay (shape, rendering, Win32)
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

One capability is an opt-in extra rather than a default install: listening
to what the computer is *playing* ("resume ce que dit cette video") needs
WASAPI loopback, which is Windows-only and ships in a separate package.

```bash
pip install pyaudiowpatch   # Windows only; everything else works without it
```

Without it Hey Peer says it cannot listen to system audio, and nothing else
changes. It is deliberately not in `requirements.txt`: the package has no
macOS or Linux wheel, so requiring it would break `pip install` for
everyone not on Windows.

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

Set `HEYPEER_WAKEWORD_DEBUG=1` for a live mic dB meter and per-chunk detection
score in the console, useful when diagnosing a microphone problem.

The detection threshold defaults to `0.9`. It was briefly 0.55, as a workaround
for a model trained on synthetic speech whose false positives outscored many
true ones — with that model a permissive first stage plus a strict verifier was
the only workable arrangement. A model personalised on your own voice separates
the classes properly, so the threshold does real work again. Detection remains a
two-stage cascade (see below), which is why 0.9 rather than 0.95: a missed
activation costs you a repeat, while a false one is caught by the verifier
moments later. Override with `HEYPEER_WAKEWORD_THRESHOLD`.

For debugging with the console visible (or on a headless box without a tray
host), use the foreground console loop instead:

```bash
python -m heypeer.main --cli
```

This always runs with capture and voice activation both on, falls back to
pressing Enter to simulate the wake word if no trained model is available, and
still shows a real (detached) tray icon so "Quitter" works as a stop button
instead of Task Manager. **The actual conversation (wake word detected, instruction
heard, resolved intent, result) is logged to the terminal.** A short chime plays
once the wake word is *confirmed* (see the cascade below) — audible confirmation
that it really heard you, the way Siri/Alexa do, played on its own thread so it
never delays the start of recording — and a
visual indicator (`heypeer/tray/debug_window.py`) slides down from the top edge of
the screen like a notification: a blue → violet → magenta gradient blob with an
organic morphing silhouette, whose palette and drift speed shift per state and
whose size swells with your live voice level. It slides back up and hides between
turns, rather than sitting on screen permanently.

It has genuinely no window border and soft, glowing edges: the frame is drawn
with PIL (`heypeer/tray/blob_render.py`) and composited into the desktop through
`UpdateLayeredWindow` (`heypeer/tray/overlay.py`), which gives real per-pixel
alpha. Earlier versions tried to get this out of a web view — transparency there
still showed the host window's grey background, and clipping with `SetWindowRgn`
works but is a 1-bit mask, so edges came out hard and a glow was impossible. The
overlay is click-through and never takes focus. Windows-only; elsewhere it
degrades to a no-op. Rendered via `pywebview` (the
OS's own web view, WebView2 on Windows) loading
`heypeer/tray/webui/conversation.html`, in its own OS process (not just a thread)
specifically so that if window creation ever hangs or fails on some machine, the
rest of Hey Peer keeps running unaffected instead of the whole app freezing.

Hey Peer mutes its own wake-word listening (`WakeWordListener.mute()`/`unmute()`) for
the whole duration of a turn — from the instant a wake word is detected through
transcription, interpretation, execution, and any spoken narration — not just while
it's speaking. This is mic *gating*, not true acoustic echo cancellation (nothing is
cancelled during genuinely simultaneous playback+speech), but it covers both of the
practical problems it was built for: some headsets otherwise picked Hey Peer's own
TTS back up as more input, and separately, real logs showed the wake-word listener
re-triggering on background chatter while a previous turn was still being processed
— Hey Peer now fully finishes one turn (like Alexa/Siri) before it can hear a new
"Hey Peer" at all.

Local transcription (`heypeer/wakeword/stt.py`) uses faster-whisper's "small" model
with a French-biased prompt and voice-activity filtering (`vad_filter=True`) — after
"base" produced both garbled short words/filenames and outright hallucinated
sentences over background noise with no real speech in them.

**When you stop talking is measured, not assumed.** The end of a spoken
instruction is detected relative to the room's own noise floor (sampled from the
audio just before you started speaking) rather than at a fixed decibel level — a
fixed cutoff is either too high to hear a quiet speaker or too low to ignore a
fan, and it was truncating real instructions mid-sentence. Trailing silence has
to last ~1.2s to end a recording, since people pause naturally between a filename
and a destination.

**Wake-word detection is a two-stage cascade**, the same architecture real
always-listening assistants use. The small always-on ONNX detector only *proposes*:
because it was trained on synthetic speech only (see Status below), it fires on
plenty of ordinary speech, and no threshold separates that from real activations —
its false-positive scores are higher than many true positives. So the listener also
keeps a 2-second rolling prebuffer (the wake word is already over by the time
detection fires), and `heypeer/wakeword/verify.py` *confirms* against the Whisper
transcript that the audio really opens with something sounding like "Hey Peer"
before anything is acted on. Matching is fuzzy and normalized rather than a list of
spellings, since Whisper renders it "Hey Pierre" / "Hey, Peer." / "hey pir"
depending on accent and audio quality. The same step strips the wake word out of
the instruction, which previously leaked into what Nemotron saw.

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

Built incrementally during the hackathon, one commit per stage — see
[TODO.md](TODO.md) for the detailed build log and what's still open.

All core stages are implemented and unit-tested (`pytest`, 486 tests): wake-word
training/inference, the Nemotron client (**verified against the live Nebius API**,
not just mocks), direct file actions (move/rename/create/delete/undo) with
path-containment safety checks, the tray app, and the on-screen indicator.

Hey Peer holds a **conversation**, not a single command. Nemotron decides whether a
spoken turn is a file action, an ordinary answer ("comment ça va ?" -> "Très bien,
et toi ?"), or a question back for a missing piece; every answer says whether the
exchange is finished, and while it is not, the microphone stays open with no wake
word needed and the turns so far are replayed on the next one. Verified against the
live endpoint: `"deplace la facture"` -> *"Vers quel dossier ?"* -> `"dans Archives"`
resolves to a real move of `facture_mars.pdf`, and `"non merci"` afterwards closes
the exchange instead of repeating the last action.

Beyond files, Hey Peer **starts applications and plays music**. "Lance Spotify"
opens it *and* presses play — opening the app alone leaves you in silence looking
at a player that hasn't begun. "Lance Alright par Kendrick Lamar" resolves the
track through Spotify's search and opens `spotify:track:<id>`, which the desktop
app plays directly. That search needs only *application* credentials
(`SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`, free, no user login, no Premium);
without them it opens the search results and says so rather than claiming to have
started the music.

"Quelle est la météo à Paris ?" opens a web search; the query is percent-encoded
into a fixed search URL rather than the model being asked for an address, because
a search string can say anything and a URL can *go* anywhere.

Starting an app, playing music and searching the web all **end the turn** — no
follow-up window. Holding the microphone open after starting playback means
holding it open over the music, which through a headset is how Hey Peer ended up
listening to itself.

Apps are launched from a **registry**, not from whatever the model returned —
`resolve_app` refuses a name it doesn't know. Everything on that path began as a
speech transcript and then passed through a language model, so "run whatever it
said" is not an option. "Ouvre Machin" costs one turn to decline.

Two behaviours were found live and fixed in the prompt, both of which the model got
wrong by default: replaying an action already carried out earlier in the exchange
(a plain "non merci" came back as a second `delete_file`), and inventing facts it
cannot check ("quelle heure il est" -> *"Il est 14h"*). Requests outside the action
list are answered rather than bent into the nearest file action — "ouvre Spotify"
gets *"Je ne peux pas ouvrir Spotify pour l'instant."*, not a folder named Spotify.

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
- The orb indicator's actual rendered appearance — real Windows testing has
  caught two rounds of a "square"/"white rectangle" showing around the circle
  despite `pywebview`'s own transparency settings; the current fix bypasses
  that entirely with a direct Win32 color-key layered-window call, unverified
  since this sandbox has no GTK/WebKit backend for pywebview to render
  anything with at all — even non-visual construction couldn't be exercised
  here for real (only through mocks)
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
