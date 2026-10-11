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
    assert "deux" in task
    assert "Ne supprime" in task


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


def test_the_default_bug_is_put_back_before_every_run(monkeypatch, tmp_path: Path) -> None:
    """A rehearsal fixes it; a second run with nothing to diagnose has the
    agent say so on stage."""
    monkeypatch.delenv("HEYPEER_DEMO_CODE_FILE", raising=False)
    target = tmp_path / "demo_bug.py"
    monkeypatch.setattr(demo, "code_file", lambda: target)
    target.write_text("already fixed", encoding="utf-8")
    demo.ensure_code_file()
    assert "len(nombres)" in target.read_text(encoding="utf-8")


def test_the_users_own_file_is_never_overwritten(monkeypatch, tmp_path: Path) -> None:
    mine = tmp_path / "mine.py"
    mine.write_text("my code", encoding="utf-8")
    monkeypatch.setenv("HEYPEER_DEMO_CODE_FILE", str(mine))
    demo.ensure_code_file()
    assert mine.read_text(encoding="utf-8") == "my code"


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

    with patch("heypeer.demo.script", return_value=steps), patch(
        "heypeer.demo.ensure_code_file"
    ), patch.object(peer, "_speak", side_effect=speak):
        peer._run_demo()
    assert calls == ["a", "b"]
    assert peer._in_routine is False


def test_the_demo_is_not_counted_as_the_user_repeating_themselves() -> None:
    peer = _peer()
    seen = []
    steps = [demo.Step("_speak", {"text": "x"})]
    with patch("heypeer.demo.script", return_value=steps), patch(
        "heypeer.demo.ensure_code_file"
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


def test_the_flag_arms_the_demo() -> None:
    from heypeer.main import _build_peer

    assert _build_peer(demo=True)._demo_pending is True
    assert _build_peer(demo=False)._demo_pending is False



def test_the_capcut_step_uses_the_configured_sound_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEYPEER_SFX_DIR", str(tmp_path))
    step = next(s for s in demo.script() if s.method == "_run_edit_capcut")
    assert step.kwargs["folder"] == str(tmp_path)
