"""Second-stage verification that the wake word was *actually* spoken.

The always-on ONNX detector (`listener.py`) is deliberately small and cheap,
and this project's model was trained on synthetic Piper speech only — no
real human voices, no French accent. On real hardware it turned out to fire
on more or less any speech (scores of 0.97-0.99 on sentences that never
contained "Hey Peer"), because what it really learned to separate was
"synthetic speech-like audio" from "noise", not this phrase from other
phrases.

Rather than pretend a threshold tweak fixes that (the false-positive scores
are *higher* than many true positives, so no threshold separates them),
this adds the second stage real always-listening assistants use: a cheap
detector proposes, a more accurate model confirms. Hey Peer already runs
Whisper on the captured audio, so verification costs nothing extra — the
listener now also hands over the ~1.5s of audio *preceding* the trigger
(where the wake word itself lives), and the transcript of that is checked
here before anything is acted on.

Matching is fuzzy on purpose. Whisper renders "Hey Peer" a dozen different
ways depending on accent and audio quality — "Hey Pierre", "Hey Peer",
"Hé pire", "Hey, Pier.", "épeer" — and enumerating spellings is exactly the
brute-force approach the user pushed back on for yes/no confirmation. A
normalized sliding-window similarity ratio generalizes to renderings nobody
listed in advance.
"""

import difflib
import re
import unicodedata

WAKE_PHRASE = "hey peer"
# Tuned against the renderings actually observed in real logs ("Hey, Peer.",
# "Hey Pierre", "Hey Pyr", "hey pir") vs. unrelated French sentences that
# falsely triggered the detector. Low enough to accept accent/spelling
# drift, high enough that ordinary speech doesn't clear it.
SIMILARITY_THRESHOLD = 0.72
# The wake word is at the very start of the captured audio, so only the
# opening of the transcript is searched — this stops a chance match deep
# inside a long instruction from validating a false trigger.
SEARCH_PREFIX_CHARS = 28


def _normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace — so
    "Hey, Pierre." and "hé pierre" compare on equal footing."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", without_accents)).strip()


def _best_match_span(normalized: str) -> "tuple[float, int] | None":
    """Highest similarity to WAKE_PHRASE found in a sliding window over the
    start of `normalized`, plus the index just past that window (where the
    real instruction begins). Windows are sized around the phrase's length
    with slack for longer renderings like "hey pierre"."""
    if not normalized:
        return None
    haystack = normalized[:SEARCH_PREFIX_CHARS]
    best = None
    for length in range(len(WAKE_PHRASE) - 2, len(WAKE_PHRASE) + 5):
        for start in range(0, max(1, len(haystack) - length + 1)):
            window = haystack[start : start + length]
            if not window:
                continue
            ratio = difflib.SequenceMatcher(None, WAKE_PHRASE, window).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, start + length)
    return best


def contains_wake_word(text: str) -> bool:
    """Whether `text` (a transcript of the audio around a detection) really
    opens with something that sounds like "Hey Peer"."""
    match = _best_match_span(_normalize(text))
    return match is not None and match[0] >= SIMILARITY_THRESHOLD


def strip_wake_word(text: str) -> str:
    """Returns `text` with a leading "Hey Peer"-ish rendering removed, so the
    wake word doesn't leak into the instruction sent to Nemotron — a real
    bug before this existed: "Hey, Peer. Déplace le fichier 4." was passed
    through verbatim, and Nemotron resolved the truncated remainder to a
    destination folder literally named "unknown".

    Falls back to returning the text unchanged when no confident match is
    found, so a valid instruction is never silently mangled.
    """
    normalized = _normalize(text)
    match = _best_match_span(normalized)
    if match is None or match[0] < SIMILARITY_THRESHOLD:
        return text.strip()

    # Map the cut point in the normalized string back onto the original by
    # growing a prefix of `text` until its normalized form is long enough.
    # Counting characters one at a time instead looks cheaper but is wrong:
    # normalization collapses separators, so punctuation and runs of spaces
    # don't map 1:1 onto normalized characters (this shifted the cut by one
    # and ate the instruction's first letter — "Déplace" -> "éplace").
    consumed_target = match[1]
    # The best-scoring window can end mid-word: "hey pierre" scores highest
    # against "hey peer" over its first 8 characters, which would leave a
    # stray "re" glued to the front of the instruction. Always cut on a word
    # boundary instead.
    while consumed_target < len(normalized) and normalized[consumed_target] != " ":
        consumed_target += 1

    for i in range(len(text) + 1):
        if len(_normalize(text[:i])) >= consumed_target:
            return text[i:].lstrip(" ,.;:!?-—").strip()
    return ""
