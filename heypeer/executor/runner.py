"""Replays a Skill's actions via pyautogui, with an optional visual check
between steps to catch UI drift before it causes a wrong action.
"""

import time
from collections.abc import Callable

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

    def run(self, skill: Skill, n_repetitions: int) -> None:
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
