"""Tests for which wake-word model gets loaded.

Two files rather than one: training used to overwrite the committed generic
model, so a personalised run silently modified a tracked file and a pull or
checkout would clobber someone's own model.
"""

import pytest

from heypeer.wakeword import listener


def test_prefers_the_personal_model_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    user = tmp_path / "hey_peer_user.onnx"
    user.write_bytes(b"x")
    shipped = tmp_path / "hey_peer.onnx"
    shipped.write_bytes(b"x")
    monkeypatch.setattr(listener, "USER_MODEL_PATH", user)
    monkeypatch.setattr(listener, "SHIPPED_MODEL_PATH", shipped)

    assert listener.default_model_path() == user


def test_falls_back_to_the_shipped_model(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A fresh clone has no personal model and must still run."""
    shipped = tmp_path / "hey_peer.onnx"
    shipped.write_bytes(b"x")
    monkeypatch.setattr(listener, "USER_MODEL_PATH", tmp_path / "hey_peer_user.onnx")
    monkeypatch.setattr(listener, "SHIPPED_MODEL_PATH", shipped)

    assert listener.default_model_path() == shipped


def test_the_two_paths_are_distinct() -> None:
    """If they were the same file, training would clobber the tracked one -
    which is exactly the bug this split fixes."""
    assert listener.USER_MODEL_PATH != listener.SHIPPED_MODEL_PATH
    assert listener.USER_MODEL_PATH.name == "hey_peer_user.onnx"
