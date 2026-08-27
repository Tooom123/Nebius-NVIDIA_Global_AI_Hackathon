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


def test_detects_repeated_file_moves_regardless_of_filename() -> None:
    detector = PatternDetector(min_repetitions=3)
    result = None
    for i in range(3):
        result = detector.observe(
            ActionEvent(
                type=ActionType.FILE_MOVE,
                app_name="",
                window_title="/home/user/Invoices",
                src_path=f"/home/user/Downloads/invoice_{i}.pdf",
                dest_path=f"/home/user/Invoices/invoice_{i}.pdf",
            )
        )

    assert result is not None
    assert len(result.actions) == 1
    assert result.name == "Move .pdf into Invoices"


def test_single_click_repeated_does_not_trigger() -> None:
    # period=1 detection is only enabled for FILE_MOVE — a repeated single
    # click/key isn't a meaningful "skill" on its own.
    detector = PatternDetector(min_repetitions=3)
    result = None
    for _ in range(5):
        result = detector.observe(
            ActionEvent(type=ActionType.CLICK, app_name="Files", window_title="w", x=1, y=1)
        )
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
