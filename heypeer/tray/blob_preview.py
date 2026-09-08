"""Render the blob's animation to a video file, without running Hey Peer.

## Why this exists

Iterating on the indicator used to mean: launch the app on the Windows
machine, say the wake word, watch a two-second animation, decide it was
slightly wrong, change a number, launch again. That loop is slow, needs
real hardware and a microphone, and - the part that actually blocks work -
cannot be shared. A frame of it cannot be pasted into a conversation, so
"make it breathe a bit slower" was a discussion neither side could see.

This renders exactly the same frames the live indicator draws, straight to
a file, from a plain command:

    python -m heypeer.tray.blob_preview --state speaking --seconds 3

## Why it duplicates none of the animation

Every parameter comes from `debug_window.py` - `STATE_ENERGY`, the level
gains, `BASE_RADIUS` - and every frame from `blob_render.render` and
`blob_shape.radius_profile`. If this file had its own copy of the easing or
the amplitudes it would drift from the real thing within a week and become
a preview of something that no longer exists. It re-implements only the
frame *loop*, which in the live window is tangled up with a message pump, a
command queue and a slide animation that has nothing to do with how the
blob itself looks.

## Output format

MP4 through ffmpeg when it is available, since that is what pastes into a
conversation or a slide. Falls back to an animated GIF written by PIL when
it is not, so this never hard-depends on a binary the user may not have -
the same "degrade, don't fail" rule the rest of the project follows.
"""

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FPS = 30
DEFAULT_SECONDS = 3.0
DEFAULT_SIZE = 220

# A synthetic microphone level, for the states that react to one. A real
# voice is not a constant: holding the level at 1.0 shows the blob's maximum
# rather than its behaviour, which is the thing being judged.
def _simulated_level(t: float) -> float:
    """A plausible speech envelope - syllable-rate wobble under a slower
    phrase-level swell, clamped to 0..1."""
    syllables = 0.5 + 0.5 * math.sin(2 * math.pi * 3.1 * t)
    phrase = 0.55 + 0.45 * math.sin(2 * math.pi * 0.45 * t + 1.0)
    return max(0.0, min(1.0, syllables * phrase))


def frames(state: str, seconds: float, size: int, level: "float | None" = None):
    """Yields PIL frames of `state`'s animation.

    `level` pins the microphone level for every frame; the default varies it
    like real speech. Pinning is what you want when comparing two states
    side by side, varying is what you want when judging how it feels.
    """
    from heypeer.tray.blob_render import OUTLINE_ANGLES, render
    from heypeer.tray.blob_shape import radius_profile
    from heypeer.tray.debug_window import (
        BASE_RADIUS,
        LEVEL_AMPLITUDE_GAIN,
        LEVEL_GLOW_GAIN,
        LEVEL_RADIUS_GAIN,
        LEVEL_SPEED_GAIN,
        STATE_ENERGY,
    )

    if state not in STATE_ENERGY:
        raise SystemExit(
            f"unknown state {state!r} - choose one of: {', '.join(STATE_ENERGY)}"
        )

    energy = STATE_ENERGY[state]
    phase = 0.0
    total = int(seconds * FPS)
    for i in range(total):
        t = i / FPS
        mic = _simulated_level(t) if level is None else level
        gain = energy["level_gain"] * mic
        # Same composition the live window applies per frame.
        amplitude = energy["amplitude"] + LEVEL_AMPLITUDE_GAIN * gain
        speed = energy["speed"] + LEVEL_SPEED_GAIN * gain
        glow = energy["glow"] + LEVEL_GLOW_GAIN * gain
        radius = BASE_RADIUS * (1.0 + LEVEL_RADIUS_GAIN * gain)
        phase += speed / FPS
        yield render(
            size,
            radius_profile(OUTLINE_ANGLES, phase, amplitude),
            radius,
            glow=glow,
            phase=phase,
            # The aura pulses with the state's own energy rather than being
            # constant: it is the thing that says Hey Peer is active, so it
            # should be near-absent at idle and full while speaking.
            aura=min(1.0, energy["glow"] * 1.3 + gain * 0.5),
        )


def write_video(images, out_path: Path, fps: int = FPS) -> Path:
    """Writes `images` to `out_path`, as MP4 if ffmpeg is available and an
    animated GIF otherwise. Returns the path actually written, which may
    differ in extension from the one asked for."""
    images = list(images)
    if not images:
        raise SystemExit("nothing to render")

    if shutil.which("ffmpeg") is None:
        gif_path = out_path.with_suffix(".gif")
        images[0].save(
            gif_path,
            save_all=True,
            append_images=images[1:],
            duration=int(1000 / fps),
            loop=0,
            disposal=2,
        )
        return gif_path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for i, image in enumerate(images):
            # Composited onto a dark background: the frames have real alpha,
            # and MP4 has none - left transparent, ffmpeg flattens onto
            # black and the glow disappears into it.
            from PIL import Image

            backdrop = Image.new("RGBA", image.size, (24, 26, 32, 255))
            backdrop.alpha_composite(image)
            backdrop.convert("RGB").save(tmp_dir / f"{i:05d}.png")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", str(fps),
                "-i", str(tmp_dir / "%05d.png"),
                # yuv420p and even dimensions: without both, the file plays
                # in ffplay and in nothing else.
                "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                str(out_path),
            ],
            check=True,
        )
    return out_path


def main(argv: "list[str] | None" = None) -> int:
    from heypeer.tray.debug_window import STATE_ENERGY

    parser = argparse.ArgumentParser(
        prog="python -m heypeer.tray.blob_preview",
        description="Render the indicator blob to a video, without running Hey Peer.",
    )
    parser.add_argument(
        "--state", default="speaking", choices=sorted(STATE_ENERGY),
        help="which animation state to render (default: speaking)",
    )
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument(
        "--level", type=float, default=None,
        help="pin the mic level 0..1 instead of simulating speech",
    )
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument(
        "-o", "--out", type=Path, default=None,
        help="output file (default: blob_<state>.mp4 in the current directory)",
    )
    parser.add_argument(
        "--all-states", action="store_true",
        help="render every state, one file each",
    )
    args = parser.parse_args(argv)

    states = sorted(STATE_ENERGY) if args.all_states else [args.state]
    for state in states:
        out = args.out if (args.out and not args.all_states) else Path(f"blob_{state}.mp4")
        written = write_video(
            frames(state, args.seconds, args.size, args.level), out, args.fps
        )
        print(f"{state}: {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
