"""Structured intent returned by Nemotron after interpreting a voice command."""

from dataclasses import dataclass


ACTIONS = (
    "move_file",
    "rename_file",
    "create_file",
    "create_folder",
    "delete_file",
    "undo",  # revert the last file action ("annule")
    "open_app",  # start an application by name ("lance Spotify")
    "play_music",  # play something specific ("mets Alright de Kendrick Lamar")
    "search_web",  # look something up in a browser ("cherche X sur internet")
    "reply",  # nothing to do on the computer: just say `speech` back
    "ask",  # the instruction was almost understood; `question` says what's missing
    "unknown",
)

# Actions that are a spoken answer rather than something done to the machine.
# Both are handled identically; they are kept apart only because the prompt
# distinguishes them, and the distinction is worth keeping in the logs.
SPOKEN_ACTIONS = ("reply", "ask")

# What each action actually is, in the plain English used to check the
# prompt's own "Things you cannot do yet" section against reality (see
# test_nemotron_client.py's prompt-contradiction guard). Twice now, an
# action shipped in the dispatch code while the prompt still refused it in
# prose written before that action existed (round 29: apps and web search;
# round 31: the same for the weather, i.e. web search again). Both times a
# human had to say the exact sentence live before anyone noticed.
#
# This does not automate the fix - the guard test still greps prompt prose,
# which is free text and can always drift in a way no table catches - but it
# makes the *list of things to check for* follow from ACTIONS mechanically,
# so a new action missing its entry here fails on its own, right where the
# action is declared, rather than the guard test silently checking a
# now-incomplete hand-copied list forever.
ACTION_DESCRIPTIONS = {
    "move_file": "move a file",
    "rename_file": "rename a file",
    "create_file": "create a file",
    "create_folder": "create a folder",
    "delete_file": "delete a file",
    "undo": "undo",
    "open_app": "open an application",
    "play_music": "play music",
    "search_web": "search the web",
}


@dataclass(frozen=True)
class Intent:
    action: str  # one of ACTIONS
    skill_id: str | None
    n_repetitions: int
    # "move_file"/"rename_file"/"delete_file": an exact filename from the
    # directory listing given as context.
    src_filename: str | None = None
    # "move_file" only: destination folder name (created under the watched
    # directory if it doesn't exist yet).
    dest_folder: str | None = None
    # "rename_file" only: the file's new name (same folder).
    new_name: str | None = None
    # "create_file"/"create_folder" only: the new file/folder's name.
    target_name: str | None = None
    # "play_music" and "search_web": what to look for, as one search string.
    # For music, "X par Y" is flattened to "X Y" - the preposition is French
    # grammar, not part of the title, and a music search expects neither.
    query: str | None = None
    # "ask" only: the single short question to put to the user, in French.
    # Lets Hey Peer say what's actually missing ("vers quel dossier ?")
    # instead of a flat "je n'ai pas compris" that leaves them guessing.
    question: str | None = None
    # What to say out loud. Required for "reply", where it *is* the whole
    # response; optional on a file action, where it replaces the fixed
    # narration with something phrased for the actual request.
    speech: str | None = None
    # Whether the exchange is finished. False keeps the microphone open for a
    # reply with no wake word, which is what makes this a conversation rather
    # than a series of unrelated commands: Hey Peer stops listening when the
    # discussion is over or the task is done, not after every single turn.
    #
    # Defaults to True so anything that does not think about it - an older
    # answer, a parse failure - closes the exchange rather than leaving the
    # microphone open indefinitely.
    end_turn: bool = True
