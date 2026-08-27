"""Abstracted action-event types produced by the activity capture layer.

Capture only records event *types* and the active app/window — never keystroke
content — so the raw stream is safe to keep in memory and reason about locally.
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
