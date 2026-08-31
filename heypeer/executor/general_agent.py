"""Dispatching Hermes Agent (Nous Research, open-source, model-agnostic)
for general, multi-step tasks that fall outside Hey Peer's own action
registry - "cherche les meilleurs vols pour Paris le mois prochain et
fais-moi un resume", not "deplace facture.pdf vers Archives".

## Why a second agent, alongside `coding_agent.py`'s Claude Code dispatch

Different jobs. `fix_code` needs an agent that is specifically good at
editing a codebase - Claude Code. This is for open-ended tasks with no
action of their own: web research, scheduling, anything a broader tool
catalogue (Hermes documents web search, browser automation, task planning,
and cron scheduling among its built-in tools) can attempt that a fixed,
whitelisted action list cannot. Using the more general-purpose tool for the
more general-purpose job, rather than stretching `fix_code`'s agent to
cover both.

## What is and is not verified here

Same honesty as `coding_agent.py`: there is no `hermes` binary in this
project's own dev sandbox, so the exact invocation below is Hermes's
documented one-shot mode (`hermes chat -q "<prompt>"`,
https://hermes-agent.nousresearch.com/), not something run and observed
from here. `is_available()`'s PATH check is real.

## Why this is even less scoped than fix_code, and worth naming as such

`fix_code` at least confines its effect to one named file, checked before
and after (see `main.py`'s `_run_fix_code`). A general task dispatched here
has no such boundary - "cherche des vols" and "programme un rappel" are
legitimately open-ended, and this module has no way to know what Hermes's
own tool permissions allow it to do once running. There is no undo entry
for this action the way there is for `fix_code`: a general task is not
reliably a single reversible file edit, so pretending to capture "the"
change to restore would be dishonest. This is worth being explicit about
before wiring anything up to it that matters.
"""

import shutil
import subprocess
from pathlib import Path

# Same reasoning and same figure as coding_agent.AGENT_TIMEOUT_SECONDS - an
# open-ended task can take a while, and this blocks the thread handling the
# current turn for its entire duration.
AGENT_TIMEOUT_SECONDS = 300


class GeneralAgentUnavailable(RuntimeError):
    """The `hermes` CLI is not installed, or not on PATH."""


class GeneralAgentTimedOut(RuntimeError):
    """The agent did not finish within `AGENT_TIMEOUT_SECONDS`."""


def is_available() -> bool:
    return shutil.which("hermes") is not None


def run(prompt: str, cwd: Path) -> str:
    """Runs `hermes chat -q prompt` in one-shot mode with `cwd` as its
    working directory, returning its final text output.

    Raises `GeneralAgentUnavailable` if the CLI is not found and
    `GeneralAgentTimedOut` if it runs past `AGENT_TIMEOUT_SECONDS` - both
    are the caller's job to turn into a spoken message, never left to raise
    into a crash mid-turn.
    """
    hermes_path = shutil.which("hermes")
    if hermes_path is None:
        raise GeneralAgentUnavailable("the 'hermes' CLI is not on PATH")

    try:
        result = subprocess.run(  # noqa: S603
            [hermes_path, "chat", "-q", prompt],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GeneralAgentTimedOut(
            f"hermes did not finish within {AGENT_TIMEOUT_SECONDS}s"
        ) from exc

    return result.stdout.strip()
