"""Skill representation: a stored, replayable action sequence."""

from dataclasses import dataclass, field

from heypeer.capture.events import ActionEvent


@dataclass
class Skill:
    id: str
    name: str
    actions: list[ActionEvent] = field(default_factory=list)
    times_seen: int = 1
