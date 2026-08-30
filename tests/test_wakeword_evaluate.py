"""Tests for the wake-word evaluation report.

The scoring itself needs a model; the reporting logic — which is what turns
numbers into a threshold decision — is pure and tested here.
"""

from heypeer.wakeword.evaluate import report


def test_report_calls_out_clean_separation(capsys) -> None:
    """The useful question is whether any threshold splits the two classes."""
    report([0.95, 0.98, 0.99], [0.10, 0.20, 0.15])

    out = capsys.readouterr().out
    assert "Cleanly separable" in out
    assert "0.20" in out and "0.95" in out


def test_report_says_so_when_the_classes_overlap(capsys) -> None:
    """This is the state the synthetic-only model was in: negatives scoring
    above positives, so no threshold could work."""
    report([0.40, 0.95], [0.10, 0.85])

    out = capsys.readouterr().out
    assert "overlap" in out
    assert "Cleanly separable" not in out


def test_report_shows_recall_and_false_accepts_per_threshold(capsys) -> None:
    report([0.6, 0.8], [0.2, 0.7])

    out = capsys.readouterr().out
    assert "threshold" in out and "recall" in out and "false accepts" in out
    # At 0.5 both positives pass and one negative sneaks through.
    assert "100%" in out


def test_report_handles_empty_input(capsys) -> None:
    report([], [])  # must not raise

    assert "0 positive clip(s)" in capsys.readouterr().out
