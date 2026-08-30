"""Tests for the text Hey Peer hands to its voice.

Whether a voice sounds robotic is not something a test can judge. Whether it
is being handed phonemes it has never been trained on *is*, and that is the
concrete half of "comprend mal des anglicismes ou des extensions de fichier".

The reference set below is derived rather than declared: ordinary accented
French prose is phonemized, and whatever comes out is, by construction, the
set of sounds a French voice was trained on. Anything Hey Peer says that
falls outside it is a phoneme the model has never heard.
"""

import pytest

from heypeer.tray.pronounce import RESPELLINGS, for_speech

# Plain French, correctly accented, covering the vocabulary Hey Peer actually
# uses. Accents matter here: espeak reads unaccented "annee" as English, so an
# unaccented corpus would quietly admit English phonemes into the reference
# set and the assertions below would pass while proving nothing.
FRENCH_CORPUS = (
    "Le fichier est déplacé vers le dossier des archives. Je supprime la facture "
    "de mars. Bonjour, comment allez-vous aujourd'hui ? Il fait beau et le ciel "
    "est bleu. Quelle heure est-il maintenant ? J'ai créé un nouveau dossier pour "
    "ranger mes documents. Cette année, les vacances seront longues. Un deux trois "
    "quatre cinq six sept huit neuf dix zéro. Voilà, c'est fait ! Peux-tu répéter ? "
    "Très bien, et toi ? D'accord, à bientôt. Je joue la musique que tu veux. "
    "Je ne peux pas encore faire ça, désolé. Je renomme le fichier et je le mets "
    "à la corbeille."
)


@pytest.fixture(scope="module")
def phonemize():
    """espeak-ng, through the same path Piper itself uses to phonemize."""
    from piper.phonemize_espeak import EspeakPhonemizer

    phonemizer = EspeakPhonemizer()

    def run(text: str) -> str:
        return "".join(c for s in phonemizer.phonemize("fr", text) for c in s)

    return run


@pytest.fixture(scope="module")
def french_phonemes(phonemize) -> set:
    return set(phonemize(FRENCH_CORPUS))


def _foreign(phonemize, french: set, text: str) -> list:
    return sorted(set(phonemize(text)) - french)


# Sentences Hey Peer really says, each containing something espeak gets wrong.
SENTENCES = [
    "J'ouvre Spotify.",
    "Je lance Spotify et je mets la musique.",
    "Je crée le dossier Downloads.",
    "J'ouvre Windows.",
    "Je déplace README.md vers Archives.",
    "J'ouvre Firefox.",
    "Je prends un screenshot.",
    "J'ouvre Word.",
]


@pytest.mark.parametrize("sentence", SENTENCES)
def test_hey_peers_own_sentences_stay_within_french(phonemize, french_phonemes, sentence):
    """The actual fix: after respelling, every sound is one the French voice
    was trained on."""
    assert _foreign(phonemize, french_phonemes, for_speech(sentence)) == []


@pytest.mark.parametrize("sentence", SENTENCES)
def test_the_same_sentences_are_broken_without_it(phonemize, french_phonemes, sentence):
    """The other half of the pair, so the test above cannot pass vacuously:
    each of these really does leave French untreated. `ɒ`, `ɪ`, `ʊ` and `ɹ`
    are English vowels and an English r - the French model has an embedding
    for them and has never heard one."""
    assert _foreign(phonemize, french_phonemes, sentence) != []


def test_an_extension_is_spelled_out_letter_by_letter(phonemize, french_phonemes):
    """espeak reads some extensions correctly and turns others into words -
    "script.py" comes out as "pi", "rapport.docx" as "docks", "config.json"
    as a consonant cluster. Spelling them out makes all of them behave the
    same way."""
    assert for_speech("Je renomme script.py.") == "Je renomme script point P Y."
    assert for_speech("facture.pdf") == "facture point P D F"
    assert for_speech("config.json") == "config point J S O N"


def test_a_sentence_ending_in_a_full_stop_is_not_mistaken_for_an_extension():
    assert for_speech("C'est fait.") == "C'est fait."
    assert for_speech("Voilà. Autre chose ?") == "Voilà. Autre chose ?"


def test_a_decimal_number_is_left_alone():
    assert for_speech("Il en reste 3.5") == "Il en reste 3.5"


def test_an_acronym_is_spelled_out_rather_than_read_as_a_word():
    assert for_speech("Le format PDF est accepté.") == "Le format P D F est accepté."


def test_ordinary_french_is_untouched():
    """A rewrite that fires on normal speech is a rewrite that will eventually
    mangle it."""
    for line in ("Très bien, et toi ?", "Je déplace la facture vers Archives.",
                 "Je n'ai pas bien compris, peux-tu répéter ?"):
        assert for_speech(line) == line


def test_respelling_is_idempotent():
    """`for_speech` runs on whatever reaches `speak`, and nothing guarantees
    it runs only once."""
    once = for_speech("J'ouvre Spotify et README.md.")
    assert for_speech(once) == once


def test_every_respelling_in_the_table_actually_stays_in_french(phonemize, french_phonemes):
    """Guards the table itself. A new entry added by ear - the obvious way to
    add one - can easily still trip espeak's language switch; "spotifaïe"
    looks French and comes out `spˈɒtɪfˌaiː`, entirely English."""
    for word, respelling in RESPELLINGS.items():
        foreign = _foreign(phonemize, french_phonemes, respelling)
        assert foreign == [], f"{word} -> {respelling!r} leaves French: {foreign}"


def test_every_entry_is_there_because_the_original_was_broken(phonemize, french_phonemes):
    """The other side of the same guard: an entry for a word espeak already
    handles is a needless way to be wrong later."""
    for word in RESPELLINGS:
        assert _foreign(phonemize, french_phonemes, word) != [], (
            f"{word!r} does not need respelling - espeak already keeps it in French"
        )
