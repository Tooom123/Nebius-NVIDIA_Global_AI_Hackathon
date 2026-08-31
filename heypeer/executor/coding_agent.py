"""Dispatching a real coding agent to explain and fix code, instead of
Hey Peer trying to be a mediocre one itself.

## Why dispatch rather than reimplement

Nemotron, through `interpret_text`, produces one structured JSON object per
turn - it is not an agentic loop, has no tool access, and cannot iterate
("try running the tests, see what fails, adjust"). A single model call
asked to rewrite a whole function and get it right in one shot is exactly
the shape of task an actual coding agent - one with a real edit/run/verify
loop - is built for and a single completion is not. Hey Peer's job here is
to be the voice interface that starts that agent hands-free and reports
back, the same relationship it already has with Spotify: it does not
reimplement a music player, it drives one that already exists.

This project is itself built with Claude Code, so that is the agent
dispatched - `claude -p "<prompt>"`, its documented non-interactive/headless
mode, run with the watched directory as its working directory so it can
only see and touch what a normal `cd` into that folder would expose.

## What is and is not verified here

There is no `claude` binary in this project's own dev sandbox to test
against (confirmed: `claude --version` here reports "command not found"),
so the exact flags below are the current, documented behaviour of Claude
Code's headless mode as best known when this was written, **not** something
run and observed from here. `--permission-mode acceptEdits` is deliberately
the narrower choice, not `--dangerously-skip-permissions`: it auto-approves
the file edits this feature exists for, without also silently auto-approving
arbitrary shell commands the agent might otherwise decide to run. If Claude
Code's CLI has changed its flag names since, `is_available()` still
correctly detects the binary, but `run()` may need `--permission-mode`'s
exact spelling adjusted - check `claude --help` on the machine this runs on
before relying on it for anything that matters.

## Why this needs a hard timeout no other action here has

Everything else Hey Peer does finishes in well under a second. A real
coding task can genuinely take minutes, and `run()` blocks the thread
handling the current turn for as long as it runs - Hey Peer cannot hear or
respond to anything else until it returns. `AGENT_TIMEOUT_SECONDS` exists
specifically so a stuck or unexpectedly slow agent process degrades to an
honest "ca prend trop de temps" after a bounded wait, rather than leaving
Hey Peer unresponsive with no way to tell it happened short of killing the
whole app.
"""

import shutil
import subprocess
from pathlib import Path

# A real coding task can take a while - long enough that a short timeout
# would abort legitimate work, but bounded, because this blocks the thread
# handling the current turn for its entire duration. Five minutes is a
# guess at a reasonable ceiling, not a measured one - there was nothing to
# measure it against from here.
AGENT_TIMEOUT_SECONDS = 300


class CodingAgentUnavailable(RuntimeError):
    """The `claude` CLI is not installed, or not on PATH."""


class CodingAgentTimedOut(RuntimeError):
    """The agent did not finish within `AGENT_TIMEOUT_SECONDS`."""


def is_available() -> bool:
    return shutil.which("claude") is not None


def run(prompt: str, cwd: Path) -> str:
    """Runs `claude -p prompt` headlessly with `cwd` as its working
    directory, returning its final text output.

    Raises `CodingAgentUnavailable` if the CLI is not found and
    `CodingAgentTimedOut` if it runs past `AGENT_TIMEOUT_SECONDS` - both are
    the caller's job to turn into a spoken message, never left to raise
    into a crash mid-turn.
    """
    claude_path = shutil.which("claude")
    if claude_path is None:
        raise CodingAgentUnavailable("the 'claude' CLI is not on PATH")

    try:
        result = subprocess.run(  # noqa: S603
            [claude_path, "-p", prompt, "--permission-mode", "acceptEdits"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise CodingAgentTimedOut(
            f"claude did not finish within {AGENT_TIMEOUT_SECONDS}s"
        ) from exc

    return result.stdout.strip()


def open_diff_in_vscode(original_path: Path, current_path: Path) -> bool:
    """Opens VS Code's diff view comparing `original_path` (a backup of the
    file's content from before the agent touched it) against `current_path`
    (the real file, now possibly changed) - so a fix is something to review,
    not something that silently happened.

    Returns whether it actually managed to - VS Code not being on PATH is
    not treated as an error worth failing the whole turn over: the fix (and
    its undo entry) already happened either way, only the review convenience
    is missing. Uses `code` directly via `shutil.which` rather than
    `executor.apps.launch`, which has no way to pass the `--diff` arguments
    a plain "open this one thing" launch does not need anywhere else.
    """
    code_path = shutil.which("code")
    if code_path is None:
        return False
    subprocess.Popen(  # noqa: S603
        [code_path, "--diff", str(original_path), str(current_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True
