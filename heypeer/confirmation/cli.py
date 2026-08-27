"""Minimal CLI confirmation gate.

No automation may run without an explicit "yes" here — this is the one required
checkpoint between an interpreted intent and actual execution.
"""

from heypeer.nemotron.intent import Intent


def confirm(intent: Intent, skill_name: str) -> bool:
    prompt = (
        f'Hey Peer wants to run "{skill_name}" {intent.n_repetitions} more time(s). '
        "Proceed? [y/N] "
    )
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")
