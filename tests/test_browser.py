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


def test_hermes_answers_quietly(tmp_path) -> None:
    """Without -Q the whole transcript - banner, prompt, tool calls - was
    summarised aloud instead of the answer."""
    with patch("shutil.which", return_value="hermes"), patch("subprocess.run") as run:
        run.return_value.stdout = "done"
        general_agent.run("task", tmp_path)
    assert run.call_args.args[0][:4] == ["hermes", "chat", "-Q", "-q"]
    assert run.call_args.kwargs["stdin"] is not None


def test_hermes_model_can_be_chosen_for_the_demo(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HEYPEER_HERMES_MODEL", "moonshotai/Kimi-K3")
    monkeypatch.delenv("HEYPEER_HERMES_PROVIDER", raising=False)
    with patch("shutil.which", return_value="hermes"), patch("subprocess.run") as run:
        run.return_value.stdout = "done"
        general_agent.run("task", tmp_path)
    args = run.call_args.args[0]
    assert args[args.index("-m") + 1] == "moonshotai/Kimi-K3"
    assert args[args.index("--provider") + 1] == "nebius-token-factory"


def test_hermes_keeps_its_configured_model_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("HEYPEER_HERMES_MODEL", raising=False)
    with patch("shutil.which", return_value="hermes"), patch("subprocess.run") as run:
        run.return_value.stdout = "done"
        general_agent.run("task", tmp_path)
    assert "-m" not in run.call_args.args[0]


def test_a_url_fragment_survives_the_new_tab(monkeypatch) -> None:
    """A bare "#" ended the request: "#label/HeyPeer" was dropped and the
    agent landed on the whole inbox."""
    import urllib.request

    monkeypatch.setenv("HEYPEER_BROWSER_CDP_URL", "http://127.0.0.1:9222")
    seen = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"[]"

    def fake_open(request, timeout=0):
        seen.append(request.full_url if hasattr(request, "full_url") else request)
        return _Response()

    with patch.object(browser, "is_running", return_value=True), patch.object(
        urllib.request, "urlopen", side_effect=fake_open
    ), patch("json.load", return_value=[]):
        assert browser.single_tab("https://mail.google.com/mail/u/0/#label/HeyPeer")
    new = [u for u in seen if "/json/new?" in u][0]
    assert "%23label/HeyPeer" in new
