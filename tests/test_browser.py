"""The debugging Chrome Hermes drives - see `executor/browser.py`."""

from unittest.mock import patch

from heypeer.executor import browser, general_agent


def test_nothing_is_started_without_a_cdp_url(monkeypatch) -> None:
    """Hermes then uses its own browser, as before."""
    monkeypatch.delenv("HEYPEER_BROWSER_CDP_URL", raising=False)
    with patch("subprocess.Popen") as popen:
        assert browser.ensure_running() is False
    popen.assert_not_called()


def test_the_port_comes_from_the_url(monkeypatch) -> None:
    monkeypatch.setenv("HEYPEER_BROWSER_CDP_URL", "http://127.0.0.1:9333")
    assert browser._port() == 9333


def test_chrome_opens_on_its_own_profile_at_the_stage(monkeypatch, tmp_path) -> None:
    """Chrome refuses remote debugging on its default profile."""
    monkeypatch.setenv("HEYPEER_BROWSER_CDP_URL", "http://127.0.0.1:9222")
    monkeypatch.setenv("HEYPEER_BROWSER_PROFILE", str(tmp_path))
    monkeypatch.setenv("HEYPEER_BROWSER_POSITION", "-1920,0")
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("")
    with patch.object(browser, "is_running", side_effect=[False, True]), patch.object(
        browser, "_chrome", return_value=chrome
    ), patch("subprocess.Popen") as popen:
        assert browser.ensure_running() is True
    args = popen.call_args.args[0]
    assert "--remote-debugging-port=9222" in args
    assert f"--user-data-dir={tmp_path}" in args
    assert "--window-position=-1920,0" in args


def test_hermes_is_pointed_at_the_debugging_chrome(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HEYPEER_BROWSER_CDP_URL", "http://127.0.0.1:9222")
    with patch("shutil.which", return_value="hermes"), patch("subprocess.run") as run:
        run.return_value.stdout = "done"
        general_agent.run("task", tmp_path)
    assert run.call_args.kwargs["env"]["BROWSER_CDP_URL"] == "http://127.0.0.1:9222"


def test_hermes_keeps_its_own_browser_without_one(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("HEYPEER_BROWSER_CDP_URL", raising=False)
    with patch("shutil.which", return_value="hermes"), patch("subprocess.run") as run:
        run.return_value.stdout = "done"
        general_agent.run("task", tmp_path)
    assert run.call_args.kwargs["env"] is None
