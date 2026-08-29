"""Structured intent returned by Nemotron after interpreting a voice command."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    action: str  # "run_skill" | "move_file" | "unknown"
    skill_id: str | None
    n_repetitions: int
    # "move_file" only: an exact filename from the directory listing given as
    # context, and a destination folder name (created under the watched
    # directory if it doesn't exist yet).
    src_filename: str | None = None
    dest_folder: str | None = None
