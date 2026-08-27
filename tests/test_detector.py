from heypeer.capture.events import ActionEvent, ActionType
from heypeer.patterns.detector import PatternDetector


def _seq(app: str) -> list[ActionEvent]:
    return [
        ActionEvent(type=ActionType.CLICK, app_name=app, window_title="w"),
        ActionEvent(type=ActionType.KEY_PRESS, app_name=app, window_title="w"),
    ]


def test_detects_repeated_two_step_sequence() -> None:
    detector = PatternDetector(min_repetitions=3)
    result = None
    for _ in range(3):
        for event in _seq("Files"):
            result = detector.observe(event)

    assert result is not None
    assert len(result.actions) == 2
    assert "Files" in result.name


def test_no_detection_below_threshold() -> None:
    detector = PatternDetector(min_repetitions=3)
    result = None
    for _ in range(2):
        for event in _seq("Files"):
            result = detector.observe(event)

    assert result is None


def test_unrelated_events_do_not_trigger() -> None:
    detector = PatternDetector(min_repetitions=3)
    apps = ["A", "B", "C", "D", "E", "F"]
    result = None
    for app in apps:
        result = detector.observe(
            ActionEvent(type=ActionType.CLICK, app_name=app, window_title="w")
        )
    assert result is None
