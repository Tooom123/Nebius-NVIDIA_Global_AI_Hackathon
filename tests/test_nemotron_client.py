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


def test_interpret_text_parses_move_file_intent_with_watched_files() -> None:
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {
                "action": "move_file",
                "src_filename": "facture_mars.pdf",
                "dest_folder": "Archives",
            }
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret_text(
            "déplace le fichier facture vers Archives",
            skill_context=[],
            watched_files=["facture_mars.pdf", "notes.txt"],
        )

    assert intent.action == "move_file"
    assert intent.src_filename == "facture_mars.pdf"
    assert intent.dest_folder == "Archives"
    assert intent.n_repetitions == 1  # default when the model omits it

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "facture_mars.pdf" in user_message
    assert "notes.txt" in user_message


def test_interpret_text_parses_rename_file_intent() -> None:
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "rename_file", "src_filename": "facture.pdf", "new_name": "facture_mars.pdf"}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret_text(
            "renomme facture.pdf en facture_mars.pdf",
            skill_context=[],
            watched_files=["facture.pdf"],
        )

    assert intent.action == "rename_file"
    assert intent.src_filename == "facture.pdf"
    assert intent.new_name == "facture_mars.pdf"


def test_interpret_text_parses_create_folder_intent() -> None:
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "create_folder", "target_name": "Factures"}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret_text("crée un dossier Factures", skill_context=[])

    assert intent.action == "create_folder"
    assert intent.target_name == "Factures"


def test_interpret_text_parses_delete_file_intent() -> None:
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "delete_file", "src_filename": "notes.txt"}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret_text(
            "supprime notes.txt", skill_context=[], watched_files=["notes.txt"]
        )

    assert intent.action == "delete_file"
    assert intent.src_filename == "notes.txt"


def test_interpret_text_includes_watched_folders_in_context() -> None:
    """Regression test: without an existing-folder listing, Nemotron had no
    way to know a folder like "test" already existed and would sometimes
    invent a plausible-but-wrong variant (e.g. "tests") instead."""
    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "move_file", "src_filename": "6.txt", "dest_folder": "test"}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        client.interpret_text(
            "déplace 6.txt dans le dossier test",
            skill_context=[],
            watched_files=["6.txt"],
            watched_folders=["test", "Archives"],
        )

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "test" in user_message
    assert "Archives" in user_message


def test_interpret_text_with_screenshot_uses_list_content(tmp_path) -> None:
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"fake-png-bytes")

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
        client.interpret_text(
            "do it again", skill_context=[], screenshot_path=str(screenshot_path)
        )

    content = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert [p["type"] for p in content] == ["text", "image_url"]
    assert "do it again" in content[0]["text"]


def test_interpret_sends_audio_and_screenshot_with_watched_files(tmp_path) -> None:
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"fake-png-bytes")

    settings = Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {
                "action": "move_file",
                "src_filename": "facture_mars.pdf",
                "dest_folder": "Archives",
            }
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret(
            str(audio_path),
            str(screenshot_path),
            skill_context=[],
            watched_files=["facture_mars.pdf", "notes.txt"],
        )

    assert intent.action == "move_file"
    assert intent.src_filename == "facture_mars.pdf"

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    content_parts = call_kwargs["messages"][1]["content"]
    types = [p["type"] for p in content_parts]
    assert types == ["text", "input_audio", "image_url"]
    assert "facture_mars.pdf" in content_parts[0]["text"]
    assert content_parts[1]["input_audio"]["format"] == "wav"


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
