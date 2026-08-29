"""Minimal CLI confirmation gate.

No automation may run without an explicit "yes" here — this is the one required
checkpoint between an interpreted intent and actual execution.
"""

from heypeer.nemotron.intent import Intent


def confirm(intent: Intent, description: str) -> bool:
    suffix = f" (x{intent.n_repetitions})" if intent.n_repetitions > 1 else ""
    prompt = f"Hey Peer wants to: {description}{suffix}. Proceed? [y/N] "
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")
