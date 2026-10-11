"""Sound design for the user's latest CapCut project.

"Ouvre mon dernier CapCut et rajoute des bruitages adaptés parmi ceux de
tel dossier": Hey Peer watches the video, decides which sound goes where,
puts those sounds into the CapCut project, then shows the result full
screen.

## The three halves, and who decides what

* **Watching** - `sample_frames` pulls a handful of stills out of the video
  with ffmpeg, timestamped. The vision model describes what happens at each
  one (`NemotronClient.describe_video_frames`). A 20-second motion design
  changes every second or two, so eight to twelve frames see every beat.
* **Deciding** - Nemotron reads that timeline and the *names* of the sound
  files and writes the cue sheet: which file at which second
  (`NemotronClient.compose_sound_cues`). The sounds are the user's own, so
  their file names ("whoosh_long.wav", "pop_2.mp3") are the only
  description of them there is, and the model is told exactly that.
  `clean_cues` then throws away anything that names a file that is not in
  the folder or a time outside the video. The model picks; it never invents
  a path.
* **Doing** - two outputs from the same cue sheet:
  - `apply_to_draft` writes the sounds into the CapCut project as audio
    tracks, so opening the project shows them on the timeline where the
    user can keep editing. This uses `pycapcut`, which writes CapCut's own
    draft schema. It only works on drafts CapCut stores as plain JSON:
    CapCut International does, the Chinese JianYing build encrypts them
    from 6.0 on, and an encrypted draft is reported, not touched.
  - `render_command` mixes the same sounds onto the video with ffmpeg,
    preceded by a transition from a screenshot of the desktop, and
    `play_fullscreen` shows that. This is what the audience sees, and it
    does not depend on CapCut's export, which cannot be driven reliably
    from outside.

## Not touching the user's work

CapCut rewrites its draft from memory as it autosaves, so a draft edited
while CapCut has it open is overwritten moments later. The draft is written
with CapCut closed (`close_app`, a normal window close - CapCut saves on
close), and a copy of the original sits beside it as
`<draft>.heypeer-backup.json` before anything is written. Added tracks are
named "Hey Peer SFX n" so they are recognisable and easy to delete.
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac")

# Draft files CapCut has used, newest layout first. Desktop builds have
# written the timeline to both names over time; whichever is present is the
# one CapCut reads.
DRAFT_FILES = ("draft_content.json", "draft_info.json")

FRAME_COUNT = 10
FRAME_WIDTH = 640

# A cue every second and a half is already busy for a 20-second piece;
# more than this is the model decorating every frame, and the result
# sounds like a sound-effects library being browsed.
MAX_CUES = 14

SFX_VOLUME = 0.9

# The transition into the finished video: the desktop as it was, giving
# way to the motion design. Long enough to read as a transition, short
# enough that the video starts before anyone wonders what is happening.
TRANSITION = "zoomin"
TRANSITION_SECONDS = 0.8
INTRO_HOLD_SECONDS = 1.0

BACKUP_SUFFIX = ".heypeer-backup.json"
TRACK_PREFIX = "Hey Peer SFX"


@dataclass(frozen=True)
class Cue:
    time: float  # seconds into the video
    sound: Path


# --- Finding the project ----------------------------------------------------


def drafts_root() -> Path:
    """Where CapCut keeps its projects. HEYPEER_CAPCUT_DRAFTS overrides it,
    for a non-default install or a rehearsal copy."""
    configured = os.environ.get("HEYPEER_CAPCUT_DRAFTS")
    if configured:
        return Path(configured).expanduser()
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def draft_file(draft_dir: Path) -> "Path | None":
    for name in DRAFT_FILES:
        path = draft_dir / name
        if path.is_file():
            return path
    return None


def latest_draft(root: "Path | None" = None) -> "Path | None":
    """The most recently edited project folder, or None.

    By the draft file's modification time rather than the folder's: CapCut
    touches the folder for thumbnails and caches, the draft only when the
    edit itself changes - which is what "my last CapCut" means.
    """
    root = root or drafts_root()
    if not root.is_dir():
        return None
    candidates = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        path = draft_file(child)
        if path is not None:
            candidates.append((path.stat().st_mtime, child))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def load_draft(path: Path) -> "dict | None":
    """The draft as a dict, or None when it is not plain JSON - which, for
    a file CapCut wrote, means it is encrypted."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def main_video(content: dict) -> "Path | None":
    """The video the project is built on: the longest video material whose
    file still exists. Longest because a motion design project often holds
    short overlays too, and the sounds belong on the main piece."""
    videos = (content.get("materials") or {}).get("videos") or []
    best = None
    for item in videos:
        if not isinstance(item, dict) or item.get("type", "video") != "video":
            continue
        path = item.get("path")
        if not path or not Path(path).is_file():
            continue
        duration = item.get("duration") or 0
        if best is None or duration > best[0]:
            best = (duration, Path(path))
    return best[1] if best else None


def sounds_in(folder: Path) -> "list[Path]":
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def find_folder(spoken: "str | None") -> "Path | None":
    """The sound folder the user named.

    An absolute path is taken as is. A bare name ("mes bruitages", "SFX") is
    looked for in the places people keep media, two levels deep, matched
    without case. HEYPEER_SFX_DIR is the fallback - and for the demo, the
    answer, so a misheard folder name cannot end the take.
    """
    if spoken:
        direct = Path(spoken).expanduser()
        if direct.is_absolute() and direct.is_dir():
            return direct
        needle = spoken.strip().lower()
        home = Path.home()
        for base in ("Music", "Musique", "Downloads", "Desktop", "Documents", "Videos", "Vidéos"):
            root = home / base
            if not root.is_dir():
                continue
            for depth in ("*", "*/*"):
                for candidate in root.glob(depth):
                    if candidate.is_dir() and candidate.name.lower() == needle:
                        return candidate
    configured = os.environ.get("HEYPEER_SFX_DIR")
    if configured and Path(configured).expanduser().is_dir():
        return Path(configured).expanduser()
    return None


# --- Watching ----------------------------------------------------------------


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _probe(path: Path, entries: str, stream: "str | None" = None) -> str:
    command = ["ffprobe", "-v", "error"]
    if stream:
        command += ["-select_streams", stream]
    command += ["-show_entries", entries, "-of", "default=nw=1:nk=1", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def duration_of(path: Path) -> float:
    try:
        return float(_probe(path, "format=duration").splitlines()[0])
    except (ValueError, IndexError, OSError, subprocess.SubprocessError):
        return 0.0


def has_audio(path: Path) -> bool:
    try:
        return bool(_probe(path, "stream=index", "a"))
    except (OSError, subprocess.SubprocessError):
        return False


def video_size(path: Path) -> "tuple[int, int]":
    try:
        width, height = _probe(path, "stream=width,height", "v:0").splitlines()[:2]
        return int(width), int(height)
    except (ValueError, OSError, subprocess.SubprocessError):
        return (1920, 1080)


def frame_times(duration: float, count: int = FRAME_COUNT) -> "list[float]":
    """Evenly spaced, centred in each slice - never frame 0, which in a
    motion design is usually a blank or a fade from black."""
    if duration <= 0 or count <= 0:
        return []
    step = duration / count
    return [round(step * (i + 0.5), 2) for i in range(count)]


def sample_frames(video: Path, count: int = FRAME_COUNT) -> "list[tuple[float, bytes]]":
    """`(seconds, png bytes)` for each sampled frame, scaled down: the
    vision model needs to see what is happening, not the pixels, and ten
    full-HD PNGs in one request is a slow request."""
    frames = []
    for t in frame_times(duration_of(video), count):
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(video),
             "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2",
             "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            frames.append((t, result.stdout))
    return frames


# --- Deciding ----------------------------------------------------------------


def clean_cues(raw, sounds: "list[Path]", duration: float) -> "list[Cue]":
    """The model's cue sheet, keeping only what can be carried out.

    A sound is matched by file name or by stem, without case - the model
    sometimes drops the extension. Anything else is discarded rather than
    guessed at: a cue for a file that does not exist is the model inventing
    a path, and nothing here opens a path a model made up.
    """
    if not isinstance(raw, list):
        return []
    by_name = {}
    for sound in sounds:
        by_name.setdefault(sound.name.lower(), sound)
        by_name.setdefault(sound.stem.lower(), sound)

    cues = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("sound")
        t = item.get("time")
        if not isinstance(name, str) or isinstance(t, bool) or not isinstance(t, (int, float)):
            continue
        sound = by_name.get(Path(name.strip()).name.lower()) or by_name.get(Path(name.strip()).stem.lower())
        if sound is None or not 0 <= t < duration:
            continue
        key = (round(float(t), 1), sound)
        if key in seen:
            continue
        seen.add(key)
        cues.append(Cue(round(float(t), 2), sound))
    cues.sort(key=lambda c: c.time)
    return cues[:MAX_CUES]


def fallback_cues(sounds: "list[Path]", times: "list[float]") -> "list[Cue]":
    """Used only when the model returns nothing usable: one sound per
    sampled moment, cycling through the folder. Ordinary, and said to be in
    the log - but a demo that adds no sound at all is worse."""
    if not sounds:
        return []
    return [Cue(t, sounds[i % len(sounds)]) for i, t in enumerate(times[::2])]


def lanes(cues: "list[Cue]", lengths: "dict[Path, float]") -> "list[list[Cue]]":
    """Groups cues onto as few tracks as possible without two overlapping
    on one track - CapCut, like any editor, refuses overlapping clips on a
    track. Greedy, first lane that is free, which is optimal for intervals
    sorted by start."""
    result: "list[list[Cue]]" = []
    ends: "list[float]" = []
    for cue in sorted(cues, key=lambda c: c.time):
        end = cue.time + lengths.get(cue.sound, 1.0)
        for i, lane_end in enumerate(ends):
            if cue.time >= lane_end:
                result[i].append(cue)
                ends[i] = end
                break
        else:
            result.append([cue])
            ends.append(end)
    return result


# --- Doing: the CapCut project ----------------------------------------------


def close_app(timeout: float = 8.0) -> bool:
    """Closes CapCut the way a user would, and returns whether it is closed.

    A window close, not a process kill: CapCut saves on close, and killing
    it could lose an edit made seconds ago. Already closed is success.
    """
    try:
        import uiautomation as auto
    except ImportError:
        return True
    try:
        window = auto.WindowControl(searchDepth=1, Name="CapCut")
        if not window.Exists(maxSearchSeconds=0.5):
            window = auto.WindowControl(searchDepth=1, SubName="CapCut")
        if not window.Exists(maxSearchSeconds=0.5):
            return True
        window.GetWindowPattern().Close()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not window.Exists(maxSearchSeconds=0.2):
                return True
            time.sleep(0.3)
        return False
    except Exception:
        return False


def apply_to_draft(path: Path, cues: "list[Cue]", video_seconds: float) -> int:
    """Writes the cues into the draft as audio tracks and returns how many
    were placed. Raises on anything that stops it, after which the draft is
    untouched - the backup is made first and the file is written once, at
    the end.

    Each clip runs for the length of its sound, cut at the end of the
    video, so a long tail does not extend the project.
    """
    import pycapcut as cc

    backup = path.with_name(path.stem + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)

    script = cc.ScriptFile.load_template(str(path))
    materials = {sound: cc.AudioMaterial(str(sound)) for sound in {c.sound for c in cues}}
    lengths = {sound: m.duration / cc.SEC for sound, m in materials.items()}
    end_us = int(video_seconds * cc.SEC)

    placed = 0
    for index, lane in enumerate(lanes(cues, lengths), start=1):
        name = f"{TRACK_PREFIX} {index}"
        script.add_track(cc.TrackType.audio, name)
        for cue in lane:
            start = int(cue.time * cc.SEC)
            length = min(materials[cue.sound].duration, end_us - start)
            if length <= 0:
                continue
            segment = cc.AudioSegment(
                materials[cue.sound], cc.Timerange(start, length), volume=SFX_VOLUME
            )
            script.add_segment(segment, name)
            placed += 1
    script.save()
    return placed


def open_app() -> bool:
    try:
        from heypeer.executor import apps

        app = apps.resolve_app("capcut")
        if app is None:
            return False
        apps.launch(app)
        return True
    except Exception:
        return False


# --- Doing: what the audience sees ------------------------------------------


def render_command(
    video: Path,
    cues: "list[Cue]",
    output: Path,
    *,
    intro_image: "Path | None" = None,
    size: "tuple[int, int]" = (1920, 1080),
    video_has_audio: bool = True,
    video_seconds: float = 0.0,
) -> "list[str]":
    """The ffmpeg command that mixes the cues onto the video, preceded by a
    transition from `intro_image` when one is given.

    Pure - builds the arguments, runs nothing - so the filter graph, which
    is where every mistake in an ffmpeg command lives, can be tested
    without ffmpeg.

    With an intro, the screenshot is held for INTRO_HOLD_SECONDS and then
    gives way to the video through TRANSITION; every sound is delayed by
    the same offset so it still lands on its frame.
    """
    width, height = size
    norm = f"scale={width}:{height}:force_original_aspect_ratio=decrease," \
           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"

    inputs: "list[str]" = []
    filters: "list[str]" = []
    offset = 0.0
    if intro_image is not None:
        offset = INTRO_HOLD_SECONDS
        hold = INTRO_HOLD_SECONDS + TRANSITION_SECONDS
        inputs += ["-loop", "1", "-t", f"{hold}", "-i", str(intro_image)]
        inputs += ["-i", str(video)]
        filters.append(f"[0:v]{norm}[intro]")
        filters.append(f"[1:v]{norm}[main]")
        filters.append(
            f"[intro][main]xfade=transition={TRANSITION}:"
            f"duration={TRANSITION_SECONDS}:offset={INTRO_HOLD_SECONDS}[v]"
        )
        video_index = 1
    else:
        inputs += ["-i", str(video)]
        filters.append(f"[0:v]{norm}[v]")
        video_index = 0

    mix = []
    if video_has_audio:
        ms = int(offset * 1000)
        filters.append(f"[{video_index}:a]adelay={ms}|{ms}[orig]")
        mix.append("[orig]")
    first_sfx = video_index + 1
    for i, cue in enumerate(cues):
        inputs += ["-i", str(cue.sound)]
        ms = int((cue.time + offset) * 1000)
        filters.append(f"[{first_sfx + i}:a]adelay={ms}|{ms},volume={SFX_VOLUME}[s{i}]")
        mix.append(f"[s{i}]")

    maps = ["-map", "[v]"]
    if mix:
        filters.append(
            f"{''.join(mix)}amix=inputs={len(mix)}:duration=longest:normalize=0[a]"
        )
        maps += ["-map", "[a]"]

    command = ["ffmpeg", "-y", "-v", "error", *inputs,
               "-filter_complex", ";".join(filters), *maps,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-b:a", "192k"]
    # The picture's own end is the end. Not -shortest: on a video with no
    # soundtrack the shortest stream is the mixed sounds, and -shortest cut
    # a six-second test clip at 3.7 seconds, where the last sound ended.
    if video_seconds > 0:
        command += ["-t", f"{offset + video_seconds:.2f}"]
    command.append(str(output))
    return command


def screenshot(path: Path) -> "Path | None":
    """The primary screen as it is, for the transition to start from."""
    try:
        from PIL import ImageGrab

        ImageGrab.grab().save(path)
        return path
    except Exception:
        return None


def render(video: Path, cues: "list[Cue]", output: Path, intro_image: "Path | None" = None) -> bool:
    command = render_command(
        video, cues, output, intro_image=intro_image,
        size=video_size(video), video_has_audio=has_audio(video),
        video_seconds=duration_of(video),
    )
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and output.is_file()


def play_fullscreen(path: Path) -> bool:
    """Plays `path` full screen and returns once it has finished.

    ffplay, which ships with ffmpeg, because it can be told to go full
    screen, borderless, and to exit at the end - the default player can be
    asked for none of that. Without it, the file opens in the default
    player, which is still the right video, just not full screen.
    """
    player = shutil.which("ffplay")
    if player:
        try:
            subprocess.run(
                [player, "-fs", "-autoexit", "-noborder", "-loglevel", "quiet", str(path)],
                timeout=600,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
        return True
    except (AttributeError, OSError):
        return False
