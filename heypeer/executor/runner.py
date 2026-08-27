"""Replays a Skill's actions via pyautogui, with a visual check between steps.

Replay logic and the Nemotron visual-verification callback land in a later step;
this module defines the interface consumed by the rest of the pipeline.
"""

from heypeer.patterns.skill import Skill


class SkillRunner:
    def __init__(self, verify_each_step: bool = True) -> None:
        self.verify_each_step = verify_each_step

    def run(self, skill: Skill, n_repetitions: int) -> None:
        raise NotImplementedError("Skill execution not implemented yet")
