"""A local, closed-vocabulary shortcut for the single most common class of
instruction, tried before Nemotron ever sees the transcript.

## Why this exists

Every recognised instruction, however trivial, has always cost one full
network round trip to a remote LLM before anything happens - the single
biggest, most direct latency the user has actually reported, repeatedly,
across this whole project's history. "Supprime facture.pdf" does not need a
language model to understand what it means.

## Why it is this narrow, and why that is deliberate

The temptation is to make this "understand file commands" in general. It
does not: it matches exactly three fixed sentence shapes - delete, rename,
move - built from the single most specific verb Nemotron's own prompt lists
for each ("supprime"/"efface", "renomme ... en", "deplace ... vers"), never
the wider synonym lists ("mets", "range", "place", "fous", "colle", "envoie",
"balance", "glisse", "appelle", ...) the prompt also accepts for the exact
same actions.

That is not laziness - the prompt's own module docstring names the reason
this module cannot safely widen: several of those synonyms are shared
verbatim across different actions ("mets" moves a file *and* starts a
follow-up conversational reply pattern; "lance" starts an app, plays a
track, *and* moves a file - "the object decides", per that prompt). Telling
those apart from a bare word requires exactly the semantic judgement an LLM
exists for. A regex that tried would eventually move a file when the user
meant to launch Spotify, which is a far worse outcome than the network round
trip this module exists to save. Comprehension regressions are the one
thing this project's own history keeps flagging as worse than latency - see
the "j'ai l'impression qu'elle comprend moins bien" reports through this
project's rounds. Staying narrow is what keeps this module's mistakes at
zero rather than trading one complaint for the other.

## Why the fast path does no filename matching of its own

`runner.resolve_existing_filename` already turns an approximate spoken name
into a real one (exact, case-insensitive, stem, prefix, then fuzzy) - and
`move_single_file`/`rename_file`/`delete_file` already call it themselves.
Duplicating that logic here would be a second implementation to keep in sync
with the first, solving nothing. Instead, this module extracts the raw
spoken filename and checks it resolves *before* returning an `Intent` at
all: a candidate that does not resolve is not "close enough, fix it later"
- it is silently declined, and the instruction falls through to Nemotron
exactly as if this module were not here. This is also what makes an
otherwise-tricky edge case harmless by construction: a filename that happens
to contain a standalone "en" or "vers" (rare, but possible) can make a
pattern below split it in the wrong place, but the wrong candidate then
fails to resolve, and the instruction still reaches Nemotron correctly - it
only costs the round trip this module was trying to save, never a wrong
answer.

## Where this must never run

Only ever tried by the caller on a *fresh* turn (empty conversation
history), never inside a follow-up window - see the call site in
`main.py`. A pronoun-only continuation ("et le deuxieme aussi") cannot be
parsed by a fixed sentence shape and would not match regardless, but a
follow-up turn is exactly the case where an LLM's grasp of what "aussi"
refers to matters, so it is excluded structurally rather than relying on
these patterns simply failing to match.
"""

import re

from heypeer.executor.runner import resolve_existing_filename
from heypeer.nemotron.intent import Intent

# `(?:le fichier )?` absorbs the filler word people actually say
# ("supprime le fichier facture.pdf"); trailing punctuation is Whisper's,
# not the user's, and is stripped rather than required. `d[ée]place` covers
# both spellings a transcript might produce for the one accented verb in
# this list - the rest have none.
_DELETE = re.compile(r"^(?:supprime|efface)\s+(?:le\s+fichier\s+)?(.+?)\s*[.!?]*$", re.IGNORECASE)
_RENAME = re.compile(
    r"^renomme\s+(?:le\s+fichier\s+)?(.+?)\s+en\s+(.+?)\s*[.!?]*$", re.IGNORECASE
)
_MOVE = re.compile(
    r"^d[ée]place\s+(?:le\s+fichier\s+)?(.+?)\s+vers\s+(.+?)\s*[.!?]*$", re.IGNORECASE
)


def try_fast_path(text: str, watched_dir, watched_folders: "list[str] | None" = None) -> "Intent | None":
    """Returns an `Intent` for `text` without calling Nemotron, or None to
    fall back to it - None covers "did not look like one of these three
    shapes" and "looked like one, but the named file does not exist" alike,
    since both mean the same thing to the caller: try the real thing.
    """
    if not text or watched_dir is None:
        return None

    match = _DELETE.match(text)
    if match:
        (raw_name,) = match.groups()
        resolved = resolve_existing_filename(watched_dir, raw_name)
        if resolved is None:
            return None
        return Intent(
            action="delete_file",
            skill_id=None,
            n_repetitions=1,
            src_filename=raw_name,
            speech=f"Je supprime {resolved}.",
            end_turn=True,
        )

    match = _RENAME.match(text)
    if match:
        raw_name, new_name = match.groups()
        resolved = resolve_existing_filename(watched_dir, raw_name)
        if resolved is None:
            return None
        return Intent(
            action="rename_file",
            skill_id=None,
            n_repetitions=1,
            src_filename=raw_name,
            new_name=new_name.strip(),
            speech=f"Je renomme {resolved} en {new_name.strip()}.",
            end_turn=True,
        )

    match = _MOVE.match(text)
    if match:
        raw_name, raw_dest = match.groups()
        resolved = resolve_existing_filename(watched_dir, raw_name)
        if resolved is None:
            return None
        dest_folder = _resolve_dest_folder(raw_dest.strip(), watched_folders)
        if dest_folder is None:
            return None
        return Intent(
            action="move_file",
            skill_id=None,
            n_repetitions=1,
            src_filename=raw_name,
            dest_folder=dest_folder,
            speech=f"Je déplace {resolved} vers {dest_folder}.",
            end_turn=True,
        )

    return None


def _resolve_dest_folder(spoken: str, watched_folders: "list[str] | None") -> "str | None":
    """The real, existing folder `spoken` case-insensitively names, or None.

    Deliberately narrower than it could be: `.+?` in `_MOVE` captures
    everything up to end of string, including a trailing clause a real
    sentence has and a bare folder name doesn't ("vers Archives s'il te
    plait"). There is no `watched_dir`-listing equivalent to check that
    against the way a filename gets checked - inventing one (word-count
    limits, a stopword list) would be exactly the kind of "close enough,
    probably fine" guess this whole module refuses to make. Requiring the
    destination to already exist sidesteps the problem instead of solving
    it: a real folder name matches exactly, "Archives s'il te plait" matches
    nothing and declines cleanly - and moving into a *new* folder, the one
    real case this gives up on, still reaches Nemotron correctly, which
    already resolves it fine today.
    """
    if not watched_folders:
        return None
    for folder in watched_folders:
        if folder.lower() == spoken.lower():
            return folder
    return None
