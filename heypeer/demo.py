"""The scripted demo run - `python -m heypeer.main --cli --demo`.

## What this is, stated plainly

A safety net for a three-minute stage demo. With `--demo`, the first
"Hey Peer" of the session runs this fixed sequence whatever was said after
it; every turn after that is ordinary Hey Peer again.

It exists because a live demo has one take. Speech recognition in a noisy
room, a model routing one sentence to the wrong action, a pause read as the
end of a turn - each is rare, and across eight instructions on stage one of
them is likely. The sequence below removes the *interpretation* step and
nothing else.

That boundary matters, and is worth saying to anyone who asks: every step
calls the same handler the spoken path calls. The drums are composed by
Nemotron from the tempo, the code is diagnosed by Nemotron and fixed by the
coding agent, the mail and the playlist are carried out by the general
agent. What is scripted is *which* instructions run and in what order - not
what they do once they run.

## Editing it

`script()` is the whole sequence, in order. Each step names a `HeyPeer`
method and its arguments, so reordering the demo is moving a line and
adding to it is writing one. The few things that depend on the demo
machine - which file holds the bug, who receives the playlist - come from
environment variables with defaults, so the run can be rehearsed on one
machine and performed on another without editing code.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Step:
    """One thing the demo does: a `HeyPeer` method and what to pass it."""

    method: str
    kwargs: dict = field(default_factory=dict)


def code_file() -> Path:
    """The file with the bug the demo fixes. HEYPEER_DEMO_CODE_FILE, else
    `demo_bug.py` beside the project - created by `ensure_code_file` so a
    fresh machine has something to fix."""
    configured = os.environ.get("HEYPEER_DEMO_CODE_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent / "demo_bug.py"


# The bug the demo fixes when no file is configured. Deliberately the one a
# room recognises in a second - an average that divides by zero on an empty
# list - so the audience is following the fix, not reading the code.
DEFAULT_BUGGY_CODE = '''def moyenne(nombres):
    total = 0
    for n in nombres:
        total += n
    return total / len(nombres)


print(moyenne([12, 15, 18]))
print(moyenne([]))
'''


def ensure_code_file() -> Path:
    """Puts the bug back before every run.

    Always rewritten rather than checked: a rehearsal fixes it, and a second
    run with nothing to diagnose has the agent say so on stage. Detecting
    "already fixed" would mean guessing what shape the agent's fix took.

    Only the default file. A path from HEYPEER_DEMO_CODE_FILE is the user's
    own code and is never written to by this.
    """
    path = code_file()
    if not os.environ.get("HEYPEER_DEMO_CODE_FILE"):
        path.write_text(DEFAULT_BUGGY_CODE, encoding="utf-8")
    return path


def contact() -> str:
    return os.environ.get("HEYPEER_DEMO_CONTACT") or "Tally"


def playlist_name() -> str:
    return os.environ.get("HEYPEER_DEMO_PLAYLIST") or "Love"


def drum_style() -> str:
    return os.environ.get("HEYPEER_DEMO_STYLE") or ""


def mail_task() -> str:
    """What the general agent is asked to do with the inbox. Spelled out
    rather than left as "lis mes mails": an agent given a vague task on
    stage improvises, and improvising means asking questions."""
    return (
        "Ouvre https://mail.google.com dans le navigateur. Lis les derniers "
        "e-mails reçus dans la boîte de réception. Choisis-en deux qui "
        "appellent une réponse et réponds à chacun avec un message court, "
        "cordial et adapté à ce qu'il dit, puis envoie les deux réponses. "
        "Ne supprime et n'archive rien."
    )


def playlist_task() -> str:
    """The playlist and the message, as one task for the general agent -
    they are one intention, and splitting them would make the agent find the
    playlist link again in a second session."""
    return (
        f"Crée une playlist Spotify nommée « {playlist_name()} » avec une "
        "quinzaine de chansons d'amour connues. Copie le lien de partage de "
        f"la playlist, puis ouvre WhatsApp et envoie ce lien à {contact()} "
        "avec un petit message tendre d'une phrase."
    )


def script(language: str = "fr") -> "list[Step]":
    """The demo, in order."""
    path = code_file()
    return [
        Step("_speak", {"text": "C'est parti.", "language": language}),
        # FL Studio: drums composed by Nemotron from the tempo, then play.
        Step("_run_add_drums", {"narration": None, "language": language,
                                "style": drum_style()}),
        Step("_demo_play_flstudio", {"language": language}),
        # Gmail: read, reply to two.
        Step("_run_general_task", {"task": mail_task(), "language": language,
                                   "narration": "Je passe à tes mails, je lis "
                                                "les derniers et je réponds à deux."}),
        # Code: open it, diagnose it, fix it, commit and push it.
        Step("_demo_open_in_vscode", {"path": str(path), "language": language}),
        Step("_run_analyze_code", {"filename": str(path), "language": language,
                                   "question": "Qu'est-ce qui ne va pas dans ce code ?",
                                   "narration": None}),
        Step("_run_fix_code", {"filename": str(path), "language": language,
                               "question": "Corrige ce bug.", "narration": None}),
        Step("_run_commit_and_push", {"narration": None, "language": language,
                                      "cwd": str(path.parent)}),
        # The playlist, sent on WhatsApp.
        Step("_run_general_task", {"task": playlist_task(), "language": language,
                                   "narration": f"Dernière chose : une playlist "
                                                f"{playlist_name()} pour {contact()}."}),
    ]
