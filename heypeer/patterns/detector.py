"""Detects repeated action sequences in a stream of captured events.

Approach: keep a rolling buffer of recent events and, after each new event,
check whether the tail of the buffer consists of the same block of length
`period` (2..max_period) repeated `min_repetitions` times back-to-back. This is
deliberately simple — sufficient to catch the one demonstrable repeated
sequence in the demo scenario (e.g. "select file, rename, move" done 3 times)
without needing a general-purpose sequence-mining algorithm.
"""

import hashlib

from heypeer.capture.events import ActionEvent
from heypeer.patterns.skill import Skill

MAX_PERIOD = 10


def _signature(event: ActionEvent) -> tuple[str, str, str]:
    return (event.type.value, event.app_name, event.window_title)


class PatternDetector:
    def __init__(self, min_repetitions: int = 3, max_period: int = MAX_PERIOD) -> None:
        self.min_repetitions = min_repetitions
        self.max_period = max_period
        self._buffer: list[ActionEvent] = []

    def observe(self, event: ActionEvent) -> Skill | None:
        """Feed one event; returns a newly detected Skill once the repetition
        threshold is reached, otherwise None."""
        self._buffer.append(event)

        # Longest matching period first: a longer repeated block is a more
        # specific, more useful skill than a coincidental short one it contains.
        for period in range(self.max_period, 1, -1):
            window = period * self.min_repetitions
            if len(self._buffer) < window:
                continue
            segment = self._buffer[-window:]
            block = [_signature(e) for e in segment[:period]]
            repeats_match = all(
                [_signature(e) for e in segment[i * period : (i + 1) * period]] == block
                for i in range(self.min_repetitions)
            )
            if repeats_match:
                skill = self._make_skill(segment[:period])
                self._buffer.clear()
                return skill

        return None

    def _make_skill(self, actions: list[ActionEvent]) -> Skill:
        digest = hashlib.sha256(
            "|".join(str(_signature(e)) for e in actions).encode()
        ).hexdigest()[:10]
        app_names = {e.app_name for e in actions if e.app_name}
        name = f"Repeated sequence in {', '.join(sorted(app_names)) or 'unknown app'}"
        return Skill(id=f"skill_{digest}", name=name, actions=list(actions), times_seen=1)
