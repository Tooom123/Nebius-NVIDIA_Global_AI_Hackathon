"""Structured intent returned by Nemotron after interpreting a voice command."""

from dataclasses import dataclass


ACTIONS = (
    "run_skill",
    "move_file",
    "rename_file",
    "create_file",
    "create_folder",
    "delete_file",
    "undo",  # revert the last file action ("annule")
    "ask",  # the instruction was almost understood; `question` says what's missing
    "unknown",
)


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
