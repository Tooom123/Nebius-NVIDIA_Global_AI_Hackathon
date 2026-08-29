"""Structured intent returned by Nemotron after interpreting a voice command."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    action: str  # "run_skill" | "move_file" | "rename_file" | "create_file" | "create_folder" | "delete_file" | "unknown"
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
