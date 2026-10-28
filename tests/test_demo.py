"""The scripted demo run - see `heypeer/demo.py`.

The test that matters most is the first one: every step must bind to the
real signature of the method it names. A wrong argument name in a script
is otherwise found exactly once - on stage.
"""

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

from heypeer import demo
from heypeer.main import HeyPeer


def test_every_step_binds_to_the_method_it_names() -> None:
    for step in demo.script():
        method = getattr(HeyPeer, step.method, None)
        assert method is not None, f"no such step: {step.method}"
        inspect.signature(method).bind(None, **step.kwargs)


def test_the_sequence_is_the_one_asked_for() -> None:
    """FL Studio and drums, the mail, the code, the playlist, then CapCut -
    in that order."""
    methods = [s.method for s in demo.script()]
    order = [
        methods.index("_run_add_drums"),
        methods.index("_demo_play_flstudio"),
        methods.index("_run_general_task"),
        methods.index("_run_analyze_code"),
        methods.index("_run_fix_code"),
        methods.index("_run_commit_and_push"),
        len(methods) - 1 - methods[::-1].index("_run_general_task"),
        methods.index("_run_edit_capcut"),
    ]
    assert order == sorted(order)
    assert methods[-1] == "_run_edit_capcut", "it ends on the full-screen video"


def test_the_mail_task_replies_to_two_and_deletes_nothing() -> None:
    task = demo.mail_task()
    assert "mail.google.com" in task
    assert "two" in task
    assert "Do not delete" in task


def test_the_mail_is_answered_in_its_own_language() -> None:
    """The instructions are in English; a French mail still gets a French
    reply."""
    assert "language of the email" in demo.mail_task()


def test_a_dry_run_sends_nothing(monkeypatch) -> None:
    monkeypatch.setenv("HEYPEER_DEMO_DRY_RUN", "1")
    assert "Do NOT click Send" in demo.mail_task()
    assert "do NOT press Enter" in demo.playlist_task()


def test_a_real_run_sends(monkeypatch) -> None:
    monkeypatch.delenv("HEYPEER_DEMO_DRY_RUN", raising=False)
    assert "Send both replies" in demo.mail_task()
    assert "Send it" in demo.playlist_task()


def test_the_demo_is_in_english_by_default(monkeypatch) -> None:
    monkeypatch.delenv("HEYPEER_DEMO_LANGUAGE", raising=False)
    first = demo.script()[0]
    assert first.kwargs == {"text": "Let's go.", "language": "en"}


def test_only_the_tagged_steps_run(monkeypatch) -> None:
    monkeypatch.setenv("HEYPEER_DEMO_ONLY", "code, capcut")
    tags = {s.tag for s in demo.selected(demo.script())}
    assert tags == {"code", "capcut"}


def test_every_step_has_a_known_tag() -> None:
    assert all(s.tag in demo.TAGS for s in demo.script())


def test_the_playlist_goes_to_the_configured_contact(monkeypatch) -> None:
    monkeypatch.setenv("HEYPEER_DEMO_CONTACT", "Tally")
    monkeypatch.setenv("HEYPEER_DEMO_PLAYLIST", "Love")
    task = demo.playlist_task()
    assert "Love" in task and "Tally" in task and "WhatsApp" in task


def test_the_commit_happens_where_the_fixed_file_is(monkeypatch, tmp_path: Path) -> None:
    bug = tmp_path / "repo" / "bug.py"
    monkeypatch.setenv("HEYPEER_DEMO_CODE_FILE", str(bug))
    commit = next(s for s in demo.script() if s.method == "_run_commit_and_push")
    assert commit.kwargs["cwd"] == str(bug.parent)


def test_the_bug_is_put_back_before_every_run(monkeypatch, tmp_path: Path) -> None:
    """A rehearsal fixes it; a second run with nothing to diagnose has the
    agent say so on stage. A configured file is rewritten too - it is the
    demo's own throwaway file."""
    target = tmp_path / "demo_bug.py"
    monkeypatch.setenv("HEYPEER_DEMO_CODE_FILE", str(target))
    target.write_text("already fixed", encoding="utf-8")
    demo.ensure_code_file()
    assert "len(numbers)" in target.read_text(encoding="utf-8")


def test_the_bug_is_committed_so_the_fix_is_a_diff(monkeypatch, tmp_path: Path) -> None:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    monkeypatch.setenv("HEYPEER_DEMO_CODE_FILE", str(repo / "demo_bug.py"))

    demo.ensure_code_file()
    demo.ensure_code_file()  # nothing new: no second commit

    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                         capture_output=True, text=True, check=True).stdout
    assert len(log.splitlines()) == 1


# --- in HeyPeer ---

def _peer() -> HeyPeer:
    return HeyPeer(nemotron=MagicMock(), get_instruction=lambda: "n'importe quoi")


def test_the_first_turn_runs_the_demo_whatever_was_said() -> None:
    peer = _peer()
    peer._demo_pending = True
    with patch.object(peer, "_run_demo") as run_demo, patch.object(
        peer, "_dispatch_intent"
    ) as dispatch:
        peer.on_wake_word()
    run_demo.assert_called_once()
    dispatch.assert_not_called()


def test_the_demo_turn_makes_no_model_call() -> None:
    """On stage, a slow or failing endpoint would delay or abort the very
    turn the demo exists to make reliable."""
    peer = _peer()
    peer._demo_pending = True
    with patch.object(peer, "_run_demo"):
        peer.on_wake_word()
    peer.nemotron.interpret_text.assert_not_called()


def test_the_demo_is_one_shot() -> None:
    """Every turn after the first is ordinary Hey Peer again."""
    peer = _peer()
    peer._demo_pending = True
    with patch.object(peer, "_run_demo") as run_demo, patch.object(
        peer, "_dispatch_intent"
    ) as dispatch:
        peer.on_wake_word()
        peer.on_wake_word()
    run_demo.assert_called_once()
    dispatch.assert_called_once()


def test_a_failing_step_does_not_stop_the_demo() -> None:
    peer = _peer()
    calls = []
    steps = [demo.Step("_speak", {"text": "a"}), demo.Step("_speak", {"text": "b"})]

    def speak(text, language="fr"):
        calls.append(text)
        if text == "a":
            raise RuntimeError("boom")

    with patch("heypeer.demo.script", return_value=steps), patch.object(
        peer, "_prepare_demo"
    ), patch.object(peer, "_speak", side_effect=speak):
        peer._run_demo()
    assert calls == ["a", "b"]
    assert peer._in_routine is False


def test_the_demo_is_not_counted_as_the_user_repeating_themselves() -> None:
    peer = _peer()
    seen = []
    steps = [demo.Step("_speak", {"text": "x"})]
    with patch("heypeer.demo.script", return_value=steps), patch.object(
        peer, "_prepare_demo"
    ), patch.object(peer, "_speak", side_effect=lambda *a, **k: seen.append(peer._in_routine)):
        peer._run_demo()
    assert seen == [True]


def test_playback_presses_space_in_a_focused_fl_studio() -> None:
    peer = _peer()
    with patch("heypeer.executor.flstudio.focus_window", return_value=True), patch(
        "heypeer.executor.cursor_control.press_key"
    ) as press:
        peer._demo_play_flstudio()
    press.assert_called_once_with(0x20)


def test_playback_is_skipped_without_fl_studio() -> None:
    peer = _peer()
    with patch("heypeer.executor.flstudio.focus_window", return_value=False), patch(
        "heypeer.executor.cursor_control.press_key"
    ) as press:
        peer._demo_play_flstudio()
    press.assert_not_called()


def test_commit_uses_the_directory_it_is_given(tmp_path: Path) -> None:
    peer = _peer()
    with patch("heypeer.executor.coding_agent.is_available", return_value=True), patch(
        "heypeer.executor.coding_agent.run", return_value=""
    ) as run, patch.object(peer, "_speak"):
        peer._run_commit_and_push(None, "fr", cwd=str(tmp_path))
    assert run.call_args.args[1] == tmp_path


def test_commit_pre_approves_git_and_nothing_wider(tmp_path: Path) -> None:
    """In `-p` mode nobody can approve a shell command, so without this the
    commit is silently denied."""
    from heypeer.executor import coding_agent

    peer = _peer()
    with patch("heypeer.executor.coding_agent.is_available", return_value=True), patch(
        "heypeer.executor.coding_agent.run", return_value=""
    ) as run, patch.object(peer, "_speak"):
        peer._run_commit_and_push(None, "fr", cwd=str(tmp_path))
    tools = run.call_args.args[2]
    assert tools == coding_agent.GIT_TOOLS
    assert "Bash(git commit:*)" in tools and "Bash(git push:*)" in tools
    assert not any("reset" in t or t == "Bash(git:*)" for t in tools)


def test_the_flag_arms_the_demo() -> None:
    from heypeer.main import _build_peer

    assert _build_peer(demo=True)._demo_pending is True
    assert _build_peer(demo=False)._demo_pending is False



def test_the_capcut_step_uses_the_configured_sound_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEYPEER_SFX_DIR", str(tmp_path))
    step = next(s for s in demo.script() if s.method == "_run_edit_capcut")
    assert step.kwargs["folder"] == str(tmp_path)


def _drums_peer():
    peer = _peer()
    peer.nemotron.compose_drums.return_value = ([0, 4, 8, 12], [4, 12], "")
    return peer


def _drum_patches(rows):
    return [
        patch("heypeer.executor.cursor_control.is_supported", return_value=True),
        patch("heypeer.executor.flstudio.launch", return_value=True),
        patch("heypeer.executor.flstudio.dismiss_load_problems", return_value=False),
        patch("heypeer.executor.flstudio.focus_window", return_value=True),
        patch("heypeer.executor.flstudio.maximize_window", return_value=True),
        patch("heypeer.executor.flstudio.find_window", return_value=(0, 0, 1920, 1080)),
        patch("heypeer.executor.flstudio.see_channel_rack", return_value=rows),
        patch("heypeer.executor.cursor_control.cursor_position", return_value=(0, 0)),
    ]


def test_drums_say_so_rather_than_click_blind_when_the_rack_is_hidden(monkeypatch) -> None:
    """Guessed positions clicked into the wrong channels and opened their
    plugin windows - an honest sentence is the better failure."""
    from contextlib import ExitStack

    monkeypatch.setenv("HEYPEER_FL_ROWS", "7,8")
    peer = _drums_peer()
    with ExitStack() as stack:
        for p in _drum_patches([]):
            stack.enter_context(p)
        click = stack.enter_context(patch("heypeer.executor.cursor_control.click_at"))
        speak = stack.enter_context(patch.object(peer, "_speak"))
        stack.enter_context(patch.object(peer, "_animate_cursor"))
        peer._run_add_drums(None, "en")
    click.assert_not_called()
    assert "channel rack" in speak.call_args.args[0]


def test_drums_light_and_clear_steps_in_the_configured_rows(monkeypatch) -> None:
    from contextlib import ExitStack

    from heypeer.executor import flstudio

    monkeypatch.setenv("HEYPEER_FL_ROWS", "1,2")
    rows = [flstudio.StepRow(y=100 + 30 * i, xs=tuple(500 + 16 * s for s in range(16)),
                             lit=tuple(s == 1 for s in range(16))) for i in range(3)]
    peer = _drums_peer()
    with ExitStack() as stack:
        for p in _drum_patches(rows):
            stack.enter_context(p)
        stack.enter_context(patch("time.sleep"))
        click = stack.enter_context(patch("heypeer.executor.cursor_control.click_at"))
        stack.enter_context(patch.object(peer, "_speak"))
        stack.enter_context(patch.object(peer, "_animate_cursor"))
        peer._run_add_drums(None, "en")
    calls = {(c.args[0], c.args[1], c.kwargs["button"]) for c in click.call_args_list}
    # Row 1: steps 0,4,8,12 lit, the stray step 1 cleared; row 0 untouched.
    assert (516, 130, "right") in calls and (500, 130, "left") in calls
    assert (516, 160, "right") in calls and (564, 160, "left") in calls
    assert not any(y == 100 for _, y, _ in calls)


def test_the_agent_is_kept_in_one_tab() -> None:
    """Left alone it opened a tab per action, nineteen in one task, while
    the window showed the first."""
    for task in (demo.mail_task(), demo.playlist_task()):
        assert "never call new_tab()" in task


def test_the_agent_must_check_its_own_work() -> None:
    """It once reported two drafts written without having opened an email."""
    assert "check on the page" in demo.mail_task()


def test_browser_steps_start_on_their_page() -> None:
    starts = [s.kwargs.get("start_url") for s in demo.script() if s.method == "_run_general_task"]
    assert starts == [demo.mail_url(), "https://open.spotify.com"]
