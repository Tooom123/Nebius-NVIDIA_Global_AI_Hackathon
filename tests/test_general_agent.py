"""Tests for dispatching Hermes Agent to handle a general, multi-step task.

Mirrors `test_coding_agent.py` exactly - same reasoning, same limits: no
`hermes` binary in this dev sandbox to test against for real (confirmed:
`is_available()` correctly returns False here), so what's tested is this
module's own contract, not Hermes's own behaviour.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from heypeer.executor import general_agent


def test_is_available_is_false_in_this_sandbox() -> None:
    assert general_agent.is_available() is False


def test_is_available_true_when_the_binary_is_on_path() -> None:
    with patch("shutil.which", return_value="/usr/local/bin/hermes"):
        assert general_agent.is_available() is True


def test_run_raises_when_the_cli_is_not_found() -> None:
    with patch("shutil.which", return_value=None):
        with pytest.raises(general_agent.GeneralAgentUnavailable):
            general_agent.run("research flights", Path("/some/dir"))


def test_run_invokes_hermes_in_one_shot_mode_with_the_given_cwd() -> None:
    with (
        patch("shutil.which", return_value="/usr/local/bin/hermes"),
        patch("subprocess.run") as run,
    ):
        run.return_value = MagicMock(stdout="Found three good options.\n")
        result = general_agent.run("find flights to Paris", Path("/watched/dir"))

    assert result == "Found three good options."
    call = run.call_args
    assert call.args[0] == ["/usr/local/bin/hermes", "chat", "-q", "find flights to Paris"]
    assert call.kwargs["cwd"] == "/watched/dir"
    assert call.kwargs["timeout"] == general_agent.AGENT_TIMEOUT_SECONDS


def test_run_raises_a_specific_error_on_timeout() -> None:
    with (
        patch("shutil.which", return_value="/usr/local/bin/hermes"),
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="hermes", timeout=300),
        ),
    ):
        with pytest.raises(general_agent.GeneralAgentTimedOut):
            general_agent.run("a slow task", Path("/watched/dir"))
