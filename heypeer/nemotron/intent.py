"""Structured intent returned by Nemotron after interpreting a voice command."""

from dataclasses import dataclass


ACTIONS = (
    "move_file",
    "rename_file",
    "create_file",
    "create_folder",
    "delete_file",
    "undo",  # revert the last file action ("annule")
    "reply",  # nothing to do on the computer: just say `speech` back
    "ask",  # the instruction was almost understood; `question` says what's missing
    "unknown",
)

# Actions that are a spoken answer rather than something done to the machine.
# Both are handled identically; they are kept apart only because the prompt
# distinguishes them, and the distinction is worth keeping in the logs.
SPOKEN_ACTIONS = ("reply", "ask")


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
