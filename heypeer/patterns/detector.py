"""Detects repeated action sequences in a stream of captured events.

Detection logic (sliding-window sequence matching against a repetition threshold)
lands in a later step; this module defines the interface consumed by the rest of
the pipeline.
"""

from heypeer.capture.events import ActionEvent
from heypeer.patterns.skill import Skill


class PatternDetector:
    def __init__(self, min_repetitions: int = 3) -> None:
        self.min_repetitions = min_repetitions
        self._buffer: list[ActionEvent] = []

    def observe(self, event: ActionEvent) -> Skill | None:
        """Feed one event; returns a newly detected Skill once the repetition
        threshold is reached, otherwise None."""
        raise NotImplementedError("Pattern detection not implemented yet")
