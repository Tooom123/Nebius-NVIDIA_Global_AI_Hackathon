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
agent, and the CapCut sound effects are placed by Nemotron after the
vision model has watched the video. What is scripted is *which* instructions run and in what order - not
what they do once they run.

## Editing it

`script()` is the whole sequence, in order. Each step names a `HeyPeer`
method and its arguments, so reordering the demo is moving a line and
adding to it is writing one. The few things that depend on the demo
machine - which file holds the bug, who receives the playlist - come from
environment variables with defaults, so the run can be rehearsed on one
machine and performed on another without editing code.

## Rehearsing it

`python -m heypeer.main --demo-now` runs the sequence at once, without
waiting for the wake word. HEYPEER_DEMO_ONLY="drums,code" runs only the
steps with those tags. HEYPEER_DEMO_DRY_RUN=1 has every agent stop before
anything leaves the machine - replies and messages are written, not sent -
so the outward steps can be rehearsed as often as the others.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TAGS = ("intro", "drums", "mail", "code", "playlist", "capcut")


@dataclass(frozen=True)
class Step:
    """One thing the demo does: a `HeyPeer` method and what to pass it.
    `tag` names the part of the demo it belongs to, for HEYPEER_DEMO_ONLY."""

    method: str
    kwargs: dict = field(default_factory=dict)
    tag: str = ""


def language() -> str:
    """The demo is performed in English unless HEYPEER_DEMO_LANGUAGE says
    otherwise - it decides Hey Peer's voice and the agents' instructions."""
    return (os.environ.get("HEYPEER_DEMO_LANGUAGE") or "en").strip().lower()


def dry_run() -> bool:
    return (os.environ.get("HEYPEER_DEMO_DRY_RUN") or "").strip().lower() in ("1", "true", "yes", "on")


def selected(steps: "list[Step]") -> "list[Step]":
    """The steps HEYPEER_DEMO_ONLY asks for, or all of them."""
    wanted = {t.strip().lower() for t in (os.environ.get("HEYPEER_DEMO_ONLY") or "").split(",") if t.strip()}
    if not wanted:
        return steps
    return [s for s in steps if s.tag in wanted]


def _en(lang: str, french: str, english: str) -> str:
    return english if lang == "en" else french


def code_file() -> Path:
    """The file with the bug the demo fixes. HEYPEER_DEMO_CODE_FILE, else
    `demo_bug.py` beside the project."""
    configured = os.environ.get("HEYPEER_DEMO_CODE_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent / "demo_bug.py"


# The bug the demo fixes. Deliberately the one a room recognises in a
# second - an average that divides by zero on an empty list - so the
# audience is following the fix, not reading the code.
DEFAULT_BUGGY_CODE = '''def average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)


print(average([12, 15, 18]))
print(average([]))
'''


def ensure_code_file() -> Path:
    """Puts the bug back before every run, and commits it.

    Always rewritten rather than checked: a rehearsal fixes it, and a second
    run with nothing to diagnose has the agent say so on stage. So
    HEYPEER_DEMO_CODE_FILE must name a throwaway file kept for the demo -
    whatever is in it is replaced.

    Committed when the file sits in a git repository, so the fix the agent
    commits later is a real diff against the bug rather than the file's
    first appearance. The commit is local; the demo's own push carries it.
    """
    path = code_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(DEFAULT_BUGGY_CODE.encode("utf-8"))
    if (path.parent / ".git").exists():
        git = ["git", "-C", str(path.parent)]
        subprocess.run([*git, "add", path.name], capture_output=True)  # noqa: S603, S607
        if subprocess.run([*git, "diff", "--cached", "--quiet"]).returncode != 0:  # noqa: S603, S607
            subprocess.run(  # noqa: S603, S607
                [*git, "commit", "-m", "Add an average helper"], capture_output=True
            )
    return path


def flp_file() -> "Path | None":
    """The FL Studio project the drums go into, opened by the drums step
    when FL Studio is not already up. HEYPEER_DEMO_FLP; none by default."""
    configured = os.environ.get("HEYPEER_DEMO_FLP")
    return Path(configured).expanduser() if configured else None


def contact() -> str:
    return os.environ.get("HEYPEER_DEMO_CONTACT") or "Tally"


def playlist_name() -> str:
    return os.environ.get("HEYPEER_DEMO_PLAYLIST") or "Love"


def mail_url() -> str:
    """Where the demo's mails are. A label rather than the whole inbox, so
    the agent reads the three mails set up for it and nothing private."""
    return os.environ.get("HEYPEER_DEMO_MAIL_URL") or "https://mail.google.com/mail/u/0/#label/HeyPeer"


def sfx_folder() -> str:
    """The folder of sound effects for the CapCut step. HEYPEER_SFX_DIR, a
    full path, is what `executor/capcut.find_folder` falls back to anyway;
    passing it here as well means the demo never depends on a folder name
    being found by search."""
    return os.environ.get("HEYPEER_SFX_DIR") or "SFX"


def capcut_project() -> str:
    """The CapCut project the sounds go into, by the name CapCut shows -
    HEYPEER_DEMO_CAPCUT_PROJECT. Empty means the latest one, which on a
    machine used for anything else is rarely the demo's."""
    return os.environ.get("HEYPEER_DEMO_CAPCUT_PROJECT") or ""


def drum_style() -> str:
    return os.environ.get("HEYPEER_DEMO_STYLE") or ""


# How the agent is to work in the browser, said once for both tasks. Each
# sentence is there because a run went wrong without it: nineteen tabs
# opened, one per action, while the window showed the first; and a report
# of two drafts written when no email had been opened - hence the check.
WORK_IN_THE_TAB = (
    "Work only in the browser's current tab: never call new_tab(); use "
    "goto_url(url) to navigate, and js(...), fill_input(...) or "
    "click_at_xy(...) to act on the page. Before you finish, check on the "
    "page that what you did is really there. Report only what you actually "
    "did and saw; if a step failed, say which one. Do not ask me questions."
)


def mail_task() -> str:
    """What the general agent is asked to do with the mails. Spelled out
    rather than left as "read my mail": an agent given a vague task on
    stage improvises, and improvising means asking questions."""
    if dry_run():
        finish = ("Do NOT click Send: leave both replies as drafts. If a reply "
                  "draft already exists for an email, replace its text instead "
                  "of starting another one.")
    else:
        finish = "Send both replies."
    return (
        f"The Gmail label at {mail_url()} is already open in the current tab. "
        "Read its emails. Exactly two of them call for an answer; the other "
        "is an automated message that must be left alone. For each of the "
        "two: open it, click Reply, and type a short, friendly reply in the "
        f"language of the email, signed Tom. {finish} Do not delete, archive "
        f"or label anything. {WORK_IN_THE_TAB}"
    )


def playlist_task() -> str:
    """The playlist and the message, as one task for the general agent -
    they are one intention, and splitting them would make the agent find the
    playlist link again in a second session."""
    if dry_run():
        finish = ("Type the message in the chat box but do NOT press Enter or "
                  "click Send.")
    else:
        finish = "Send it."
    return (
        "Spotify's web player (https://open.spotify.com) is already open in "
        f"the current tab. Create a playlist named \"{playlist_name()}\" and "
        "add five well-known love songs to it. Copy the playlist's "
        "share link. Then, in the same tab, go to WhatsApp Web "
        f"(https://web.whatsapp.com), open the chat with {contact()} and "
        f"write a one-sentence, tender message with the link. {finish} "
        f"{WORK_IN_THE_TAB}"
    )


def script(lang: "str | None" = None) -> "list[Step]":
    """The demo, in order."""
    lang = lang or language()
    path = code_file()
    return [
        Step("_speak", {"text": _en(lang, "C'est parti.", "Let's go."), "language": lang}, "intro"),
        # FL Studio: drums composed by Nemotron from the tempo, then play.
        Step("_run_add_drums", {"narration": None, "language": lang,
                                "style": drum_style(),
                                "project": str(flp_file() or "")}, "drums"),
        Step("_demo_play_flstudio", {"language": lang}, "drums"),
        # Gmail: read, reply to two.
        Step("_run_general_task", {"task": mail_task(), "language": lang,
                                   "start_url": mail_url(),
                                   "narration": _en(lang,
                                                    "Je passe à tes mails, je lis "
                                                    "les derniers et je réponds à deux.",
                                                    "Now your inbox: I'll read the latest "
                                                    "emails and answer the two that need it.")},
             "mail"),
        # Code: open it, diagnose it, fix it, commit and push it.
        Step("_demo_open_in_vscode", {"path": str(path), "language": lang}, "code"),
        Step("_run_analyze_code", {"filename": str(path), "language": lang,
                                   "question": _en(lang, "Qu'est-ce qui ne va pas dans ce code ?",
                                                   "What's wrong with this code?"),
                                   "narration": None}, "code"),
        Step("_run_fix_code", {"filename": str(path), "language": lang,
                               "question": _en(lang, "Corrige ce bug.", "Fix this bug."),
                               "narration": None}, "code"),
        Step("_run_commit_and_push", {"narration": None, "language": lang,
                                      "cwd": str(path.parent)}, "code"),
        # The playlist, sent on WhatsApp.
        Step("_run_general_task", {"task": playlist_task(), "language": lang,
                                   "start_url": "https://open.spotify.com",
                                   "narration": _en(lang,
                                                    f"Une playlist {playlist_name()} "
                                                    f"pour {contact()}.",
                                                    f"A {playlist_name()} playlist "
                                                    f"for {contact()}.")},
             "playlist"),
        # CapCut last: it ends on the motion design playing full screen,
        # which is the demo's closing shot.
        Step("_run_edit_capcut", {"narration": _en(lang,
                                                   "Dernière chose : j'ouvre ton dernier "
                                                   "projet CapCut et je rajoute des bruitages.",
                                                   "One last thing: I'm opening your latest "
                                                   "CapCut project and adding sound effects."),
                                  "language": lang, "folder": sfx_folder(),
                                  "project": capcut_project()}, "capcut"),
    ]
