"""Tests for dispatching a real coding agent to fix code.

There is no `claude` binary in this dev sandbox to test against for real -
confirmed directly (`is_available()` correctly returns False here). What's
tested is this module's own contract: how it invokes the subprocess, and
that it degrades honestly (unavailable, timeout) rather than hanging or
raising into a crash mid-turn - not the agent's own behaviour, which cannot
be observed from here. See the module docstring for what that means for how
much to trust the exact CLI flags used.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from heypeer.executor import coding_agent


def test_is_available_is_false_in_this_sandbox() -> None:
    """The actual, confirmed state here - no claude binary on PATH."""
    assert coding_agent.is_available() is False


def test_is_available_true_when_the_binary_is_on_path() -> None:
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        assert coding_agent.is_available() is True


def test_run_raises_when_the_cli_is_not_found() -> None:
    with patch("shutil.which", return_value=None):
        with pytest.raises(coding_agent.CodingAgentUnavailable):
            coding_agent.run("fix this", Path("/some/dir"))


def test_run_invokes_claude_in_print_mode_with_the_given_cwd() -> None:
    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run") as run,
    ):
        run.return_value = MagicMock(stdout="Fixed it.\n")
        result = coding_agent.run("fix the bug", Path("/watched/dir"))

    assert result == "Fixed it."
    call = run.call_args
    assert call.args[0][:3] == ["/usr/local/bin/claude", "-p", "fix the bug"]
    assert call.kwargs["cwd"] == "/watched/dir"
    assert call.kwargs["timeout"] == coding_agent.AGENT_TIMEOUT_SECONDS


def test_run_raises_a_specific_error_on_timeout() -> None:
    """A stuck or unexpectedly slow agent must degrade to something the
    caller can turn into a spoken message, not hang the turn-handling
    thread indefinitely - see the module docstring for why this matters
    more here than anywhere else in the project."""
    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300),
        ),
    ):
        with pytest.raises(coding_agent.CodingAgentTimedOut):
            coding_agent.run("fix the bug", Path("/watched/dir"))


def test_open_diff_in_vscode_returns_false_when_code_is_not_found() -> None:
    with patch("shutil.which", return_value=None):
        assert coding_agent.open_diff_in_vscode(Path("a"), Path("b")) is False


def test_open_diff_in_vscode_launches_the_diff_view() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/code"),
        patch("subprocess.Popen") as popen,
    ):
        result = coding_agent.open_diff_in_vscode(
            Path("/tmp/before.py"), Path("/watched/facture.py")
        )

    assert result is True
    popen.assert_called_once()
    assert popen.call_args.args[0] == [
        "/usr/bin/code", "--diff", "/tmp/before.py", "/watched/facture.py",
    ]
