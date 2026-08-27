import json
from unittest.mock import MagicMock, patch

from heypeer.config import Settings
from heypeer.nemotron.client import NemotronClient


def _fake_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    return response


def test_interpret_text_parses_intent() -> None:
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "run_skill", "skill_id": "skill_abc123", "n_repetitions": 4}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret_text(
            "do it 4 more times",
            skill_context=[{"id": "skill_abc123", "name": "Sort downloaded files"}],
        )

    assert intent.action == "run_skill"
    assert intent.skill_id == "skill_abc123"
    assert intent.n_repetitions == 4

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "nvidia/nemotron-3-nano-omni"
    user_message = call_kwargs["messages"][1]["content"]
    assert "do it 4 more times" in user_message
    assert "skill_abc123" in user_message


def test_interpret_text_unknown_intent_has_no_skill_id() -> None:
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "unknown", "skill_id": None, "n_repetitions": 1}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret_text("what's the weather", skill_context=[])

    assert intent.action == "unknown"
    assert intent.skill_id is None


def test_verify_screen_returns_ok_flag() -> None:
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"ok": False})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        result = client.verify_screen(b"fake-png-bytes", expected_context="click Save button")

    assert result is False
