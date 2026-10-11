"""Sound design for the latest CapCut project - see `heypeer/executor/capcut.py`.

The ffmpeg and pycapcut halves are exercised for real when those are
installed (they are on the dev machine), and skipped otherwise: a mocked
ffmpeg would test the mock, and the filter graph is exactly where mistakes
hide - one was found this way, a muted clip cut at 3.7 of its 6 seconds.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from heypeer.config import Settings
from heypeer.executor import capcut
from heypeer.main import HeyPeer
from heypeer.nemotron import client as nemotron_client
from heypeer.nemotron.client import NemotronClient

needs_ffmpeg = pytest.mark.skipif(
    not capcut.ffmpeg_available(), reason="ffmpeg is not installed"
)


def _draft(root: Path, name: str, content: "dict | str", filename: str = "draft_content.json") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    path = folder / filename
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


# --- Finding the project ----------------------------------------------------


def test_the_latest_project_is_the_one_edited_last(tmp_path: Path) -> None:
    old = _draft(tmp_path, "Old", {})
    new = _draft(tmp_path, "New", {})
    os.utime(old, (time.time(), time.time()))
    os.utime(new, (time.time() - 1000, time.time() - 1000))
    assert capcut.latest_draft(tmp_path).name == "Old"


def test_folders_without_a_draft_and_hidden_folders_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "Empty").mkdir()
    _draft(tmp_path, ".recycle", {})
    assert capcut.latest_draft(tmp_path) is None
    assert capcut.latest_draft(tmp_path / "missing") is None


def test_either_draft_file_name_is_found(tmp_path: Path) -> None:
    path = _draft(tmp_path, "P", {}, filename="draft_info.json")
    assert capcut.draft_file(path.parent) == path


def test_the_drafts_folder_can_be_overridden(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEYPEER_CAPCUT_DRAFTS", str(tmp_path))
    assert capcut.drafts_root() == tmp_path


def test_an_encrypted_draft_is_reported_not_parsed(tmp_path: Path) -> None:
    """JianYing 6+ encrypts drafts; what is not plain JSON is not touched."""
    path = _draft(tmp_path, "P", "Q2lwaGVydGV4dA==\x00\x01garbage")
    assert capcut.load_draft(path) is None


def test_the_main_video_is_the_longest_that_still_exists(tmp_path: Path) -> None:
    main = tmp_path / "main.mp4"
    overlay = tmp_path / "overlay.mp4"
    main.write_bytes(b"x")
    overlay.write_bytes(b"x")
    content = {"materials": {"videos": [
        {"type": "video", "path": str(overlay), "duration": 2_000_000},
        {"type": "video", "path": str(main), "duration": 20_000_000},
        {"type": "video", "path": str(tmp_path / "gone.mp4"), "duration": 99_000_000},
        {"type": "photo", "path": str(main), "duration": 50_000_000},
    ]}}
    assert capcut.main_video(content) == main
    assert capcut.main_video({}) is None


def test_only_audio_files_count_as_sounds(tmp_path: Path) -> None:
    for name in ("whoosh.WAV", "pop.mp3", "notes.txt", "clip.mp4"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in capcut.sounds_in(tmp_path)] == ["pop.mp3", "whoosh.WAV"]


def test_a_spoken_folder_name_is_found_in_the_usual_places(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "Music" / "Packs" / "SFX"
    target.mkdir(parents=True)
    monkeypatch.setattr(capcut.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("HEYPEER_SFX_DIR", raising=False)
    assert capcut.find_folder("sfx") == target
    assert capcut.find_folder(str(target)) == target


def test_an_unknown_folder_falls_back_to_the_configured_one(monkeypatch, tmp_path: Path) -> None:
    """For the demo: a misheard folder name must not end the take."""
    monkeypatch.setattr(capcut.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("HEYPEER_SFX_DIR", str(tmp_path))
    assert capcut.find_folder("does not exist") == tmp_path
    monkeypatch.delenv("HEYPEER_SFX_DIR")
    assert capcut.find_folder("does not exist") is None


# --- Watching ----------------------------------------------------------------


def test_frames_are_spread_through_the_video_and_skip_the_first() -> None:
    """Frame 0 of a motion design is usually black."""
    times = capcut.frame_times(20.0, 10)
    assert times[0] == 1.0 and times[-1] == 19.0
    assert len(times) == 10
    assert capcut.frame_times(0, 10) == []


# --- Deciding ----------------------------------------------------------------


def _sounds(tmp_path: Path) -> "list[Path]":
    sounds = [tmp_path / "whoosh.wav", tmp_path / "pop.mp3"]
    for s in sounds:
        s.write_bytes(b"x")
    return sounds


def test_cues_naming_a_file_that_is_not_there_are_dropped(tmp_path: Path) -> None:
    """Measured: the model sometimes reuses a name from its worked example.
    Nothing here opens a path a model made up."""
    sounds = _sounds(tmp_path)
    cues = capcut.clean_cues(
        [{"time": 1, "sound": "whoosh.wav"}, {"time": 2, "sound": "swoosh_fast.wav"},
         {"time": 3, "sound": "../../secret.wav"}],
        sounds, 10.0,
    )
    assert [(c.time, c.sound.name) for c in cues] == [(1.0, "whoosh.wav")]


def test_a_sound_named_without_its_extension_still_matches(tmp_path: Path) -> None:
    cues = capcut.clean_cues([{"time": 1, "sound": "POP"}], _sounds(tmp_path), 10.0)
    assert cues[0].sound.name == "pop.mp3"


def test_times_outside_the_video_and_malformed_cues_are_dropped(tmp_path: Path) -> None:
    raw = [{"time": -1, "sound": "pop"}, {"time": 10, "sound": "pop"}, {"time": True, "sound": "pop"},
           {"time": "2", "sound": "pop"}, "pop", {"time": 4.0}, {"time": 4.5, "sound": "pop"}]
    cues = capcut.clean_cues(raw, _sounds(tmp_path), 10.0)
    assert [c.time for c in cues] == [4.5]
    assert capcut.clean_cues({"cues": []}, _sounds(tmp_path), 10.0) == []


def test_cues_are_sorted_deduplicated_and_capped(tmp_path: Path) -> None:
    sounds = _sounds(tmp_path)
    raw = [{"time": t / 2, "sound": "pop"} for t in range(40, 0, -1)] + [{"time": 0.5, "sound": "pop"}]
    cues = capcut.clean_cues(raw, sounds, 30.0)
    assert len(cues) == capcut.MAX_CUES
    assert [c.time for c in cues] == sorted(c.time for c in cues)
    assert len({(c.time, c.sound) for c in cues}) == len(cues)


def test_the_fallback_still_puts_sounds_on_the_video(tmp_path: Path) -> None:
    sounds = _sounds(tmp_path)
    cues = capcut.fallback_cues(sounds, capcut.frame_times(20.0))
    assert cues and {c.sound for c in cues} == set(sounds)
    assert capcut.fallback_cues([], [1.0]) == []


def test_overlapping_cues_go_on_separate_tracks(tmp_path: Path) -> None:
    """An editor refuses two clips overlapping on one track."""
    a, b = _sounds(tmp_path)
    cues = [capcut.Cue(0.0, a), capcut.Cue(0.5, b), capcut.Cue(2.0, b)]
    lanes = capcut.lanes(cues, {a: 1.0, b: 0.3})
    assert [[c.time for c in lane] for lane in lanes] == [[0.0, 2.0], [0.5]]


# --- Doing: the preview ------------------------------------------------------


def test_the_render_command_lands_every_sound_after_the_intro(tmp_path: Path) -> None:
    a, b = _sounds(tmp_path)
    command = capcut.render_command(
        tmp_path / "v.mp4", [capcut.Cue(1.0, a), capcut.Cue(2.5, b)], tmp_path / "out.mp4",
        intro_image=tmp_path / "shot.png", video_seconds=20.0,
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=" in graph
    offset = int(capcut.INTRO_HOLD_SECONDS * 1000)
    assert f"adelay={1000 + offset}|{1000 + offset}" in graph
    assert f"adelay={2500 + offset}|{2500 + offset}" in graph
    assert "amix=inputs=3" in graph, "the original soundtrack plus two sounds"
    last_t = len(command) - 1 - command[::-1].index("-t")
    assert command[last_t + 1] == f"{20.0 + capcut.INTRO_HOLD_SECONDS:.2f}"


def test_a_silent_video_is_mixed_without_a_soundtrack_it_does_not_have(tmp_path: Path) -> None:
    a, _ = _sounds(tmp_path)
    command = capcut.render_command(
        tmp_path / "v.mp4", [capcut.Cue(1.0, a)], tmp_path / "out.mp4",
        video_has_audio=False, video_seconds=6.0,
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:a]" not in graph
    assert "amix=inputs=1" in graph
    assert "-shortest" not in command, "it cut a muted clip at its last sound"
    assert command[command.index("-t") + 1] == "6.00"


@needs_ffmpeg
def test_the_preview_really_renders_at_the_videos_length(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    sound = tmp_path / "pop.wav"
    shot = tmp_path / "shot.png"
    run = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
    run("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=3", str(video))
    run("-f", "lavfi", "-i", "sine=f=880:d=0.3", str(sound))
    run("-f", "lavfi", "-i", "color=c=red:s=640x480", "-frames:v", "1", str(shot))

    cues = [capcut.Cue(0.5, sound)]
    plain, intro = tmp_path / "plain.mp4", tmp_path / "intro.mp4"
    assert capcut.render(video, cues, plain)
    assert capcut.render(video, cues, intro, shot)
    assert abs(capcut.duration_of(plain) - 3.0) < 0.15
    assert abs(capcut.duration_of(intro) - (3.0 + capcut.INTRO_HOLD_SECONDS)) < 0.15
    assert capcut.has_audio(plain)
    assert capcut.sample_frames(video, 3) and len(capcut.sample_frames(video, 3)) == 3


# --- Doing: the project ------------------------------------------------------


@needs_ffmpeg
def test_sounds_are_written_into_the_draft_as_named_tracks(tmp_path: Path) -> None:
    cc = pytest.importorskip("pycapcut")
    try:
        import pymediainfo
        if not pymediainfo.MediaInfo.can_parse():
            pytest.skip("libmediainfo is not installed")
    except ImportError:
        pytest.skip("pymediainfo is not installed")

    video, long_sound, short_sound = tmp_path / "v.mp4", tmp_path / "whoosh.wav", tmp_path / "pop.wav"
    run = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
    run("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=4", str(video))
    run("-f", "lavfi", "-i", "sine=f=220:d=1.0", str(long_sound))
    run("-f", "lavfi", "-i", "sine=f=880:d=0.3", str(short_sound))

    script = cc.ScriptFile(1920, 1080)
    script.add_track(cc.TrackType.video)
    script.add_segment(cc.VideoSegment(cc.VideoMaterial(str(video)), cc.trange("0s", "4s")))
    path = tmp_path / "Edit" / "draft_content.json"
    path.parent.mkdir()
    script.dump(str(path))
    original = path.read_text(encoding="utf-8")

    cues = [capcut.Cue(0.5, long_sound), capcut.Cue(1.0, short_sound), capcut.Cue(3.8, long_sound)]
    assert capcut.apply_to_draft(path, cues, 4.0) == 3

    tracks = json.loads(path.read_text(encoding="utf-8"))["tracks"]
    sfx = [t for t in tracks if (t.get("name") or "").startswith(capcut.TRACK_PREFIX)]
    assert len(sfx) == 2, "the overlapping cue went on a second track"
    ends = [s["target_timerange"]["start"] + s["target_timerange"]["duration"]
            for t in sfx for s in t["segments"]]
    assert max(ends) <= 4_000_000, "a sound's tail does not extend the project"
    backup = path.with_name("draft_content" + capcut.BACKUP_SUFFIX)
    assert backup.read_text(encoding="utf-8") == original


# --- Nemotron ----------------------------------------------------------------


def _client(monkeypatch, raw: "str | Exception") -> "tuple[NemotronClient, MagicMock]":
    client = NemotronClient(
        Settings(nebius_api_key="k", nebius_base_url="http://x", nemotron_model_id="m")
    )
    create = MagicMock()
    if isinstance(raw, Exception):
        create.side_effect = raw
    else:
        create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content=raw))])
    monkeypatch.setattr(
        type(client), "_client",
        property(lambda self: MagicMock(chat=MagicMock(completions=MagicMock(create=create)))),
    )
    return client, create


def test_every_frame_goes_to_the_vision_model_with_its_time(monkeypatch) -> None:
    client, create = _client(monkeypatch, '{"timeline": "t=1.0s: a logo appears"}')
    timeline = client.describe_video_frames([(1.0, b"png1"), (3.0, b"png2")])
    assert timeline == "t=1.0s: a logo appears"
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == client.settings.vision_model_id
    content = kwargs["messages"][0]["content"]
    assert [c["text"] for c in content if c["type"] == "text"][1:] == ["t=1.0s", "t=3.0s"]
    assert sum(c["type"] == "image_url" for c in content) == 2


def test_a_timeline_written_as_a_list_is_joined(monkeypatch) -> None:
    client, _ = _client(monkeypatch, '{"timeline": ["t=1s: a", "t=2s: b"]}')
    assert client.describe_video_frames([(1.0, b"x")]) == "t=1s: a\nt=2s: b"


def test_the_cue_sheet_is_composed_with_reasoning_off(monkeypatch) -> None:
    """Measured: reasoning on, a 20-second timeline took 80 seconds and ran
    out of tokens before any JSON. Off: under three seconds."""
    client, create = _client(monkeypatch, '{"cues": [{"time": 1, "sound": "pop.wav"}]}')
    cues = client.compose_sound_cues("t=1s: pop", ["pop.wav"], 5.0)
    assert cues == [{"time": 1, "sound": "pop.wav"}]
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "m"
    assert kwargs["extra_body"] == nemotron_client.NO_THINKING
    assert "pop.wav" in kwargs["messages"][-1]["content"]


def test_failures_return_nothing_rather_than_raising(monkeypatch) -> None:
    client, _ = _client(monkeypatch, RuntimeError("down"))
    assert client.describe_video_frames([(1.0, b"x")]) == ""
    assert client.compose_sound_cues("", ["pop.wav"], 5.0) == []
    client, _ = _client(monkeypatch, "not json")
    assert client.compose_sound_cues("", ["pop.wav"], 5.0) == []


# --- In HeyPeer ---------------------------------------------------------------


def _peer() -> HeyPeer:
    peer = HeyPeer(nemotron=MagicMock(), get_instruction=lambda: "")
    peer._speak = MagicMock()
    peer._speak_async = MagicMock()
    return peer


def _spoken(peer: HeyPeer) -> str:
    return " ".join(str(c.args[0]) for c in peer._speak.call_args_list)


def test_missing_ffmpeg_is_said_not_crashed() -> None:
    peer = _peer()
    with patch.object(capcut, "ffmpeg_available", return_value=False):
        peer._run_edit_capcut(None, "fr", "SFX")
    assert "ffmpeg" in _spoken(peer)


def test_an_encrypted_project_is_left_alone(monkeypatch, tmp_path: Path) -> None:
    _draft(tmp_path, "P", "encrypted")
    monkeypatch.setenv("HEYPEER_CAPCUT_DRAFTS", str(tmp_path))
    peer = _peer()
    with patch.object(capcut, "ffmpeg_available", return_value=True), \
            patch.object(capcut, "apply_to_draft") as apply:
        peer._run_edit_capcut(None, "fr", "SFX")
    assert "chiffré" in _spoken(peer)
    apply.assert_not_called()


def test_an_empty_sound_folder_is_said(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    _draft(tmp_path / "drafts", "P", {"materials": {"videos": [{"path": str(video)}]}})
    monkeypatch.setenv("HEYPEER_CAPCUT_DRAFTS", str(tmp_path / "drafts"))
    peer = _peer()
    with patch.object(capcut, "ffmpeg_available", return_value=True), \
            patch.object(capcut, "find_folder", return_value=tmp_path / "nothing"):
        peer._run_edit_capcut(None, "fr", "SFX")
    assert "bruitages" in _spoken(peer)
    peer.nemotron.compose_sound_cues.assert_not_called()


def test_the_whole_edit_watches_decides_writes_and_shows(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    draft = _draft(tmp_path / "drafts", "P", {"materials": {"videos": [{"path": str(video)}]}})
    monkeypatch.setenv("HEYPEER_CAPCUT_DRAFTS", str(tmp_path / "drafts"))
    sfx = tmp_path / "sfx"
    sfx.mkdir()
    (sfx / "pop.wav").write_bytes(b"x")

    peer = _peer()
    peer.nemotron.describe_video_frames.return_value = "t=1s: a logo pops"
    peer.nemotron.compose_sound_cues.return_value = [{"time": 1.0, "sound": "pop.wav"}]
    with patch.object(capcut, "ffmpeg_available", return_value=True), \
            patch.object(capcut, "find_folder", return_value=sfx), \
            patch.object(capcut, "duration_of", return_value=20.0), \
            patch.object(capcut, "sample_frames", return_value=[(1.0, b"png")]), \
            patch.object(capcut, "close_app", return_value=True), \
            patch.object(capcut, "apply_to_draft", return_value=1) as apply, \
            patch.object(capcut, "open_app"), \
            patch.object(capcut, "screenshot", return_value=tmp_path / "s.png"), \
            patch.object(capcut, "render", return_value=True) as render, \
            patch.object(capcut, "play_fullscreen") as play, \
            patch("heypeer.main.time.sleep"):
        peer._run_edit_capcut(None, "fr", "SFX")

    peer.nemotron.compose_sound_cues.assert_called_once_with("t=1s: a logo pops", ["pop.wav"], 20.0)
    assert apply.call_args.args[0] == draft
    assert [c.sound.name for c in apply.call_args.args[1]] == ["pop.wav"]
    assert render.call_args.args[3] == tmp_path / "s.png", "the transition starts from the screen"
    play.assert_called_once()


def test_capcut_left_open_means_the_draft_is_not_written(monkeypatch, tmp_path: Path) -> None:
    """Its autosave would put the old timeline back seconds later."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    _draft(tmp_path / "drafts", "P", {"materials": {"videos": [{"path": str(video)}]}})
    monkeypatch.setenv("HEYPEER_CAPCUT_DRAFTS", str(tmp_path / "drafts"))
    sfx = tmp_path / "sfx"
    sfx.mkdir()
    (sfx / "pop.wav").write_bytes(b"x")
    peer = _peer()
    peer.nemotron.compose_sound_cues.return_value = []
    with patch.object(capcut, "ffmpeg_available", return_value=True), \
            patch.object(capcut, "find_folder", return_value=sfx), \
            patch.object(capcut, "duration_of", return_value=20.0), \
            patch.object(capcut, "sample_frames", return_value=[]), \
            patch.object(capcut, "close_app", return_value=False), \
            patch.object(capcut, "apply_to_draft") as apply, \
            patch.object(capcut, "open_app"), \
            patch.object(capcut, "screenshot", return_value=None), \
            patch.object(capcut, "render", return_value=True) as render, \
            patch.object(capcut, "play_fullscreen"), \
            patch("heypeer.main.time.sleep"):
        peer._run_edit_capcut(None, "fr", "")
    apply.assert_not_called()
    assert render.call_args.args[1], "the fallback still put sounds on the preview"


def test_the_action_is_dispatched_with_its_folder() -> None:
    from heypeer.nemotron.intent import Intent

    peer = _peer()
    with patch.object(peer, "_run_edit_capcut") as run:
        peer._dispatch_intent(
            Intent(action="edit_capcut", skill_id=None, n_repetitions=1, content="SFX")
        )
    run.assert_called_once()
    assert run.call_args.args[2] == "SFX"
