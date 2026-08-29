"""Replays a Skill's actions via pyautogui, with an optional visual check
between steps to catch UI drift before it causes a wrong action.

FILE_MOVE skills are replayed differently: rather than pyautogui clicks, the
executor moves the next matching files (same directory + extension the
pattern was first observed on) directly via shutil — no window position or
screen state dependency at all.
"""

import shutil
import time
from collections.abc import Callable
from pathlib import Path

from heypeer.capture.events import ActionEvent, ActionType
from heypeer.patterns.skill import Skill

# Injected by the caller (e.g. a Nemotron screenshot check). Receives the PNG
# bytes of a fresh screenshot taken right before the next action and returns
# whether it's safe to proceed.
VerifyStep = Callable[[bytes], bool]


class ExecutionAborted(RuntimeError):
    """Raised when a step-verification check fails mid-replay."""


class SkillRunner:
    def __init__(self, verify_step: VerifyStep | None = None, step_delay: float = 0.3) -> None:
        self.verify_step = verify_step
        self.step_delay = step_delay

    def _screenshot_png_bytes(self) -> bytes:
        import io

        import pyautogui

        buffer = io.BytesIO()
        pyautogui.screenshot().save(buffer, format="PNG")
        return buffer.getvalue()

    def _replay_action(self, action: ActionEvent) -> None:
        import pyautogui

        if action.type == ActionType.CLICK:
            if action.x is None or action.y is None:
                raise ExecutionAborted(f"Click action missing coordinates: {action}")
            pyautogui.click(action.x, action.y)
        elif action.type == ActionType.KEY_PRESS:
            if not action.key_name or action.key_name == "char":
                raise ExecutionAborted(
                    "Cannot replay a plain character key press — Hey Peer never "
                    "records typed content, only special keys (Enter, Tab, ...)."
                )
            pyautogui.press(action.key_name)
        elif action.type == ActionType.SCROLL:
            pyautogui.scroll(action.scroll_dy or 0)
        elif action.type in (ActionType.APP_FOCUS, ActionType.WINDOW_TITLE_CHANGE):
            pass  # Informational only — nothing to replay.

    def _run_file_move_skill(self, skill: Skill, n_repetitions: int) -> None:
        first = skill.actions[0]
        if not first.src_path or not first.dest_path:
            raise ExecutionAborted(f"File-move skill missing paths: {first}")

        source_dir = Path(first.src_path).parent
        dest_dir = Path(first.dest_path).parent
        extension = Path(first.src_path).suffix.lower()

        candidates = sorted(
            p
            for p in source_dir.iterdir()
            if p.is_file() and (not extension or p.suffix.lower() == extension)
        )
        if len(candidates) < n_repetitions:
            raise ExecutionAborted(
                f"Only {len(candidates)} matching file(s) left in {source_dir}, "
                f"need {n_repetitions}"
            )

        for path in candidates[:n_repetitions]:
            shutil.move(str(path), str(dest_dir / path.name))

    def run(self, skill: Skill, n_repetitions: int) -> None:
        if skill.actions and all(a.type == ActionType.FILE_MOVE for a in skill.actions):
            self._run_file_move_skill(skill, n_repetitions)
            return

        for _ in range(n_repetitions):
            for action in skill.actions:
                if self.verify_step is not None:
                    screenshot = self._screenshot_png_bytes()
                    if not self.verify_step(screenshot):
                        raise ExecutionAborted(
                            f"Visual verification failed before replaying {action}"
                        )
                self._replay_action(action)
                time.sleep(self.step_delay)


def move_single_file(src_path: Path, dest_dir: Path) -> Path:
    """Direct, one-off file move for the "no skill needed, pure logic"
    assistant path — not tied to a learned Skill at all. Creates `dest_dir`
    if it doesn't exist yet. Returns the file's new path."""
    if not src_path.is_file():
        raise ExecutionAborted(f"Source file not found: {src_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / src_path.name
    shutil.move(str(src_path), str(dest_path))
    return dest_path
