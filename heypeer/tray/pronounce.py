"""Rewrites text so a French voice pronounces it the way a French speaker
would say it out loud.

## The problem this solves

Piper phonemizes through espeak-ng, and espeak switches language per word:
handed "Spotify" while speaking French, it emits *English* IPA -
`spˈɒtɪfˌaɪ`. Two of those symbols, `ɒ` and `ɪ`, never occur in French. The
French voice model has an embedding for them (the phoneme table is shared
across all Piper voices) but was trained only on French speech, so it has
never heard them - the output is whatever an untrained embedding happens to
produce. That is what "comprend mal des anglicismes" sounds like.

File extensions are the same story from the other end. espeak reads some
correctly (`4.txt` -> "quatre point té ixe té") and mangles others
(`script.py` -> "pi", `rapport.docx` -> "docks", `config.json` -> a
consonant cluster with no vowel), depending on whether the letters happen to
look like a word to it.

## Why respelling, and not something cleverer

The only lever available is the input text. Piper's espeak bridge is a
compiled extension exposing three functions; it enables neither SSML
(`<voice xml:lang="fr">` comes out read aloud, word by word) nor espeak's
`[[phoneme]]` escape (spelled out letter by letter). Both were tried. There
is no flag to disable language switching either.

So each problem word is respelled in French orthography, chosen so that
espeak stays in French and produces the sounds a French speaker uses for the
English word. "Spotify" -> "spo-ti-faï" -> `spˈotˈifˈaj`.

Every entry here is verified mechanically rather than by ear: the test suite
phonemizes ordinary French prose to learn which phonemes the language
actually uses, then asserts that nothing this module emits falls outside that
set. See `tests/test_pronounce.py`.

## Known limit

An *unaccented* French word can still be anglicised - espeak reads "donnees"
as `dˈɒniːz` where "données" is correctly `dɔnˈe`. That matters for filenames,
which are whatever the user named them and cannot be re-accented. Splitting
the word was tried as an automatic repair and is unreliable ("don-nees" fixes
the first syllable and not the second), so it is not attempted: a wrong guess
that half-works is harder to reason about than a known gap. Hey Peer's own
sentences come from a model that writes accented French, so this only bites
on filenames read back.
"""

import re

# Words espeak pronounces with phonemes that do not exist in French, respelled
# so it stays in French. Keys are matched case-insensitively on word
# boundaries. Only add an entry when the word actually needs one, and the
# tests enforce that in both directions - each entry must fix a real leak, and
# must not introduce one. Plenty of what Hey Peer says already comes out fine
# and belongs nowhere near this table: Chrome, Discord, Excel, Netflix, Steam,
# Zoom, podcast, and also "YouTube" (`jˈu tˈyb`) and "playlist" (`plɛlˈist`),
# which espeak reads with a French accent - which is exactly how a French
# speaker says them.
RESPELLINGS = {
    "spotify": "spo-ti-faï",
    # "Paint" reads as "pinte" through a French voice - respelled for the
    # same reason Spotify was. Nvidia and Nebius were tried here too and
    # removed: the guard below checks each entry against espeak and said
    # both already survive in French, so respelling them would have been
    # fixing something that was not broken.
    "paint": "peïnte",
    "windows": "ouinedôze",
    "whatsapp": "ouatsape",
    "downloads": "daoune-lôdz",
    "download": "daoune-lôde",
    "readme": "ridmi",
    "word": "ouorde",
    "firefox": "faïer-fox",
    "screenshot": "scrine-chotte",
    # espeak reads this one half in each language: "pˈaʊə pwˈɛ̃", English
    # "power" glued to French "point".
    "powerpoint": "paouar-point",
    "outlook": "aoutlouk",
}

# French names of the letters, for spelling an extension out. espeak already
# names a bare capital correctly ("M" -> `ˈɛm`), so the letters are simply
# uppercased and separated rather than written phonetically.
_EXTENSION = re.compile(r"(?<=[^\W_])\.([A-Za-z][A-Za-z0-9]{0,4})(?![^\W_])")

# A standalone run of capitals is an acronym to be spelled out, not a word.
# Bounded at five so a respelled word is never caught by it.
_ACRONYM = re.compile(r"\b([A-Z]{2,5})\b")

_KNOWN = re.compile(
    r"\b(" + "|".join(sorted(RESPELLINGS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _spell_out(letters: str) -> str:
    """"txt" -> "T X T". Uppercase and separated, which is what makes espeak
    name each letter instead of guessing at a word."""
    return " ".join(letters.upper())


def for_speech(text: str) -> str:
    """`text` rewritten for a French TTS voice.

    Order matters: extensions are handled first, so "README.md" becomes
    "README point M D" and the stem is then free to be respelled on its own.
    """
    if not text:
        return text
    text = _EXTENSION.sub(lambda m: f" point {_spell_out(m.group(1))}", text)
    text = _KNOWN.sub(lambda m: RESPELLINGS[m.group(1).lower()], text)
    return _ACRONYM.sub(lambda m: _spell_out(m.group(1)), text)
