"""Tests for the local shortcut tried before Nemotron sees a transcript.

The property that actually matters here is not "does it recognise a
command" - it is "does it ever recognise the *wrong* one, or hand back a
filename that doesn't exist". A wrong local guess is worse than the network
round trip it's meant to save, so most of these tests are about the decline
path: every way this must fall back to None rather than take a guess.
"""

from pathlib import Path

import pytest

from heypeer.nemotron.fast_path import try_fast_path


@pytest.fixture
def watched_dir(tmp_path: Path) -> Path:
    (tmp_path / "facture.pdf").write_text("x")
    (tmp_path / "4.txt").write_text("x")
    (tmp_path / "Archives").mkdir()
    return tmp_path


def test_delete_matches_the_bare_verb(watched_dir: Path) -> None:
    intent = try_fast_path("supprime facture.pdf", watched_dir)

    assert intent.action == "delete_file"
    assert intent.src_filename == "facture.pdf"
    assert intent.end_turn is True


def test_delete_matches_the_other_verb_and_the_filler_word(watched_dir: Path) -> None:
    intent = try_fast_path("efface le fichier facture.pdf", watched_dir)

    assert intent.action == "delete_file"
    assert intent.src_filename == "facture.pdf"


def test_delete_absorbs_whispers_trailing_punctuation(watched_dir: Path) -> None:
    intent = try_fast_path("supprime facture.pdf.", watched_dir)

    assert intent.src_filename == "facture.pdf"


def test_delete_resolves_a_name_spoken_without_its_extension(watched_dir: Path) -> None:
    """People say "le fichier 4", not "4.txt" - this is the same real
    complaint `resolve_existing_filename` exists for; the fast path must not
    reinvent that logic, only reuse it."""
    intent = try_fast_path("supprime le fichier 4", watched_dir)

    assert intent.speech == "Je supprime 4.txt."


def test_rename_captures_both_names(watched_dir: Path) -> None:
    intent = try_fast_path("renomme facture.pdf en mars.pdf", watched_dir)

    assert intent.action == "rename_file"
    assert intent.src_filename == "facture.pdf"
    assert intent.new_name == "mars.pdf"


def test_move_captures_source_and_destination(watched_dir: Path) -> None:
    intent = try_fast_path("deplace facture.pdf vers Archives", watched_dir, ["Archives"])

    assert intent.action == "move_file"
    assert intent.src_filename == "facture.pdf"
    assert intent.dest_folder == "Archives"


def test_move_recognises_the_accented_verb_too(watched_dir: Path) -> None:
    """A transcript can come back either way depending on what Whisper
    decides - both must work identically."""
    accented = try_fast_path("déplace facture.pdf vers Archives", watched_dir, ["Archives"])
    plain = try_fast_path("deplace facture.pdf vers Archives", watched_dir, ["Archives"])

    assert accented.action == plain.action == "move_file"


def test_move_corrects_the_destination_folders_case(watched_dir: Path) -> None:
    """Extracted verbatim from speech, so a case mismatch is the only kind
    of drift possible here - unlike a model's paraphrase, there is no risk
    of it inventing the wrong plural (round 9's "test"/"tests" bug)."""
    intent = try_fast_path("deplace facture.pdf vers archives", watched_dir, ["Archives"])

    assert intent.dest_folder == "Archives"


def test_move_to_a_folder_that_does_not_exist_yet_declines(watched_dir: Path) -> None:
    """Deliberately narrower than it could be: telling a genuine new folder
    name apart from a folder name plus trailing chatter ("vers Archives
    s'il te plait") isn't reliably solvable with a fixed pattern, so this
    gives up on new folders entirely rather than risk creating one with a
    polite sentence fragment as its name. Nemotron already handles this
    case correctly today - it just costs the round trip."""
    assert try_fast_path("deplace facture.pdf vers Factures2024", watched_dir, ["Archives"]) is None


def test_move_with_no_folder_listing_at_all_declines(watched_dir: Path) -> None:
    assert try_fast_path("deplace facture.pdf vers Archives", watched_dir, None) is None


# --- Declines: the property that actually matters -------------------------


def test_an_unresolvable_filename_declines_rather_than_guessing(watched_dir: Path) -> None:
    """The central safety property: a candidate that does not resolve is
    not "close enough" - it is a decline, full stop, and the instruction
    still reaches Nemotron exactly as if this module didn't exist."""
    assert try_fast_path("supprime introuvable.pdf", watched_dir) is None


def test_a_wider_synonym_is_not_matched(watched_dir: Path) -> None:
    """"mets" is deliberately excluded, not forgotten - it also means "play
    this track" and "launch this app" elsewhere in Nemotron's own vocabulary,
    and only the model can tell those apart from the object alone."""
    assert try_fast_path("mets facture.pdf dans Archives", watched_dir) is None


def test_an_unrelated_instruction_is_not_matched(watched_dir: Path) -> None:
    for text in ("lance spotify", "comment ca va", "cherche la meteo a Paris",
                 "annule", "ouvre discord"):
        assert try_fast_path(text, watched_dir) is None


def test_empty_text_declines(watched_dir: Path) -> None:
    assert try_fast_path("", watched_dir) is None


def test_no_watched_dir_declines() -> None:
    assert try_fast_path("supprime facture.pdf", None) is None


def test_trailing_words_after_the_destination_decline_rather_than_truncate(
    watched_dir: Path,
) -> None:
    """"vers Archives s'il te plait" is not "vers Archives" - matching only
    part of what was said and silently using the rest as the folder name
    would be exactly the kind of wrong guess this module exists to avoid.
    Reusing the existing-folder check closes this rather than a bespoke
    check: "archives s'il te plait" simply matches no real folder."""
    assert try_fast_path(
        "deplace facture.pdf vers Archives s'il te plait", watched_dir, ["Archives"]
    ) is None


def test_a_standalone_en_inside_the_wrong_place_still_cannot_produce_a_bad_match(
    watched_dir: Path,
) -> None:
    """If a rename-shaped sentence happens to split at the wrong "en" (rare,
    but the pattern can't rule it out structurally), the resulting candidate
    simply fails to resolve and the decline path takes over - this is what
    makes that edge case harmless rather than something to special-case."""
    assert try_fast_path("renomme un fichier en cours en fini", watched_dir) is None
