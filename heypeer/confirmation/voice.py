"""Parses a short spoken reply into a yes/no confirmation decision.

Used after Hey Peer speaks out what it's about to do and records a brief
reply (see `heypeer.wakeword.listener.record_voice_reply`), instead of
requiring the user to type "y"/"N" into the console — the console gate
(`heypeer.confirmation.cli.confirm`) is kept as a fallback for the tray's
manual text-prompt path, where there's no recorded audio context to react
to. Accepts both French (the user's own language) and English, since
Whisper transcription auto-detects either.
"""

import re

_YES_WORDS = {
    "oui",
    "ouais",
    "ouai",
    "vasy",
    "daccord",
    "dacc",
    "confirme",
    "confirmee",
    "ok",
    "okay",
    "yes",
    "yeah",
    "yep",
    "sure",
    "confirm",
}
_NO_WORDS = {
    "non",
    "nan",
    "annule",
    "annulee",
    "stop",
    "arrete",
    "no",
    "nope",
    "cancel",
    "abort",
}


def parse_confirmation(text: str) -> "bool | None":
    """True/False for a clear yes/no, None if the reply didn't match either
    (caller decides what to do with an unclear answer - the safe default is
    to treat it as "no")."""
    normalized = re.sub(r"[^a-z ]", "", text.lower().replace("'", ""))
    tokens = normalized.split()
    if not tokens:
        return None
    if any(token in _YES_WORDS for token in tokens):
        return True
    if any(token in _NO_WORDS for token in tokens):
        return False
    return None
