"""Abstracted action-event types produced by the activity capture layer.

Capture records event types, the active app/window, and the minimal
replay-relevant metadata (click coordinates, key names, scroll deltas) needed to
physically redo an action later — but never the *content* a user typed (e.g. the
text entered into a field), so the stream stays safe to keep in memory and
reason about locally.
"""

from dataclasses import dataclass, field
from enum import Enum
from time import time


class ActionType(str, Enum):
    APP_FOCUS = "app_focus"
    CLICK = "click"
    KEY_PRESS = "key_press"
    SCROLL = "scroll"
    WINDOW_TITLE_CHANGE = "window_title_change"


@dataclass(frozen=True)
class ActionEvent:
    type: ActionType
    app_name: str
    window_title: str
    timestamp: float = field(default_factory=time)
    # Replay metadata — populated depending on `type`, left None otherwise.
    x: int | None = None
    y: int | None = None
    key_name: str | None = None
    scroll_dx: int | None = None
    scroll_dy: int | None = None
