"""Structured intent returned by Nemotron after interpreting a voice command."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    action: str
    skill_id: str | None
    n_repetitions: int
