"""Tests for the second-stage wake-word verifier.

The renderings used here are the ones Whisper actually produced in real
sessions ("Hey, Peer.", "Hey Pierre", "Hey Pyr"), plus the real French
sentences that falsely triggered the small always-on detector.
"""

import pytest

from heypeer.wakeword.verify import contains_wake_word, strip_wake_word


@pytest.mark.parametrize(
    "transcript",
    [
        "Hey Peer",
        "Hey, Peer. Déplace le fichier 4.",
        "Hey Pierre, déplace le fichier",
        "hey pir déplace 6.txt",
        "Hey Pyr, crée un dossier",
        "HEY PEER supprime notes.txt",
    ],
)
def test_recognizes_real_wake_word_renderings(transcript: str) -> None:
    assert contains_wake_word(transcript) is True


@pytest.mark.parametrize(
    "transcript",
    [
        "Déplace le fichier 4.txt dans le dossier test.",
        "Je ne suis pas compilé d'instruction.",
        "Il est gigant d'habille.",
        "",
        "   ",
    ],
)
def test_rejects_speech_without_the_wake_word(transcript: str) -> None:
    assert contains_wake_word(transcript) is False


def test_strip_removes_the_wake_word_and_leading_punctuation() -> None:
    assert strip_wake_word("Hey, Peer. Déplace le fichier 4.") == "Déplace le fichier 4."
    assert strip_wake_word("Hey Pierre, crée un dossier Factures") == "crée un dossier Factures"


def test_strip_leaves_text_untouched_when_no_wake_word_matches() -> None:
    """Never silently mangle a real instruction that just didn't match."""
    text = "Déplace le fichier 4.txt dans le dossier test."
    assert strip_wake_word(text) == text


def test_strip_of_a_bare_wake_word_yields_empty_instruction() -> None:
    assert strip_wake_word("Hey Peer") == ""


def test_wake_word_deep_inside_a_sentence_does_not_validate() -> None:
    """Only the opening of the transcript counts - the wake word is spoken
    first by construction, so a chance match late in a long instruction
    would mean a false trigger, not a real activation."""
    assert contains_wake_word("je disais a quelqu un plus tot dans la journee hey peer") is False
