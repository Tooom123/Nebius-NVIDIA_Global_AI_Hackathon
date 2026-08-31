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


def test_system_prompt_is_pure_ascii() -> None:
    """Models mirror the typography they are shown, and what they return is
    printed to a terminal and spoken aloud. A non-breaking hyphen in a
    clarifying question crashed the app on a cp1252 console, so the prompt
    itself must not demonstrate characters we don't want back."""
    from heypeer.nemotron.client import SUMMARIZE_SYSTEM_PROMPT, SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT

    for prompt in (SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT, SUMMARIZE_SYSTEM_PROMPT):
        offending = sorted({c for c in prompt if ord(c) > 127})
        assert offending == [], f"non-ASCII in prompt: {offending}"


def test_prompt_asks_for_plain_ascii_output() -> None:
    from heypeer.nemotron.client import SYSTEM_PROMPT

    assert "plain ASCII punctuation" in SYSTEM_PROMPT


def test_typographic_punctuation_is_replaced() -> None:
    """An instruction is not a guarantee - this is the net under it."""
    from heypeer.nemotron.client import _plain_punctuation

    assert _plain_punctuation("veux‑tu") == "veux-tu"  # the one that crashed it
    assert _plain_punctuation("a — b") == "a - b"
    assert _plain_punctuation("c’est") == "c'est"
    assert _plain_punctuation("bon…") == "bon..."


def test_accents_are_preserved() -> None:
    """Accents are correct French, Piper needs them to pronounce properly,
    and the console path handles them. Only pure typography is replaced."""
    from heypeer.nemotron.client import _plain_punctuation

    assert _plain_punctuation("Vers quel dossier déplacer ça ?") == "Vers quel dossier déplacer ça ?"


def test_plain_punctuation_handles_empty_values() -> None:
    from heypeer.nemotron.client import _plain_punctuation

    assert _plain_punctuation(None) is None
    assert _plain_punctuation("") == ""


def test_question_is_normalised_but_filenames_are_not() -> None:
    """Filenames must stay byte-exact to match real files on disk; the
    question is free text headed for a terminal and a speech synthesiser."""
    settings = Settings(
        nebius_api_key="k", nebius_base_url="u", nemotron_model_id="m"
    )
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {
                "action": "ask",
                "question": "Quel fichier — celui‑ci ?",
                "src_filename": "rapport‑final.txt",
            }
        )
        mock_openai_cls.return_value = mock_client
        intent = NemotronClient(settings).interpret_text("x", skill_context=[])

    assert intent.question == "Quel fichier - celui-ci ?"
    assert intent.src_filename == "rapport‑final.txt"


def test_prompt_states_that_verbs_are_examples_not_a_vocabulary() -> None:
    """Regression test: "bouge le fichier A vers B" was not understood. The
    request does go through the model - but the prompt listed exactly one
    verb per action, and a small model anchors hard on its examples. Saying
    outright that they are examples, and giving the common synonyms, is the
    fix; it is a prompt defect, not a comprehension one."""
    from heypeer.nemotron.client import SYSTEM_PROMPT

    assert "examples, not a vocabulary" in SYSTEM_PROMPT
    for synonym in ("bouge", "mets", "range", "vire", "efface", "rebaptise"):
        assert synonym in SYSTEM_PROMPT


def test_a_conversational_reply_is_parsed(monkeypatch) -> None:
    from heypeer.nemotron.client import _parse_intent

    intent = _parse_intent(
        '{"action": "reply", "speech": "Tres bien, et toi ?", "end_turn": false}'
    )

    assert intent.action == "reply"
    assert intent.speech == "Tres bien, et toi ?"
    assert intent.end_turn is False


def test_a_missing_end_turn_closes_the_exchange() -> None:
    """An open exchange keeps the microphone live with no wake word gating
    it, so that is the state a malformed or older answer must never fall
    into by omission."""
    from heypeer.nemotron.client import _parse_intent

    assert _parse_intent('{"action": "reply", "speech": "ok"}').end_turn is True
    assert _parse_intent('{"action": "reply", "end_turn": "yes"}').end_turn is True
    assert _parse_intent("not json at all").end_turn is True
    assert _parse_intent(None).end_turn is True


def test_spoken_text_gets_the_same_punctuation_treatment_as_a_question() -> None:
    """`speech` is read aloud and printed to the same console a non-breaking
    hyphen once crashed."""
    from heypeer.nemotron.client import _parse_intent

    intent = _parse_intent('{"action": "reply", "speech": "C\\u2019est fait \\u2014 voila"}')

    assert intent.speech == "C'est fait - voila"


def test_the_exchange_so_far_is_sent_between_the_system_prompt_and_the_turn() -> None:
    """Order matters: the model has to read the rules, then the conversation,
    then what was just said."""
    from unittest.mock import MagicMock

    from heypeer.config import Settings
    from heypeer.nemotron.client import SYSTEM_PROMPT, NemotronClient

    client = NemotronClient(
        Settings(nebius_api_key="k", nebius_base_url="u", nemotron_model_id="m")
    )
    client._openai_client = MagicMock()
    client._openai_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content='{"action": "unknown"}'))
    ]

    client.interpret_text(
        "et dans Archives du coup ?",
        [],
        history=[
            {"role": "user", "content": "deplace facture"},
            {"role": "assistant", "content": "Vers quel dossier ?"},
        ],
    )

    messages = client._openai_client.chat.completions.create.call_args.kwargs["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "et dans Archives du coup ?" in messages[-1]["content"]


def test_the_prompt_tells_the_model_to_answer_rather_than_guess_an_action() -> None:
    """The single most dangerous failure mode as the action list grows: an
    unsupported request ("ouvre Spotify") bent into the nearest file action,
    which touches the user's files. The instruction against it has to be in
    the prompt, not just in the reviewer's head."""
    from heypeer.nemotron.client import SYSTEM_PROMPT

    # Whitespace-normalised: this is a sentence in a wrapped paragraph, and
    # asserting on where the line breaks fall makes the test fail every time
    # the paragraph is re-wrapped without its meaning changing (round 36
    # rewrapped this exact sentence while fixing an unrelated contradiction).
    prompt = " ".join(SYSTEM_PROMPT.split())
    assert '"reply"' in prompt
    assert "do NOT invent an action name" in prompt
    assert "end_turn" in prompt


def test_the_prompt_forbids_replaying_an_action_from_earlier_in_the_exchange() -> None:
    """Found against the live endpoint, and it is the worst thing the new
    conversation memory can do: with "supprime le 15" in the history, a plain
    "non merci" came back as delete_file 15.txt again - the sign-off read as
    a repeat of the last command. Confirmed fixed by the instruction this
    asserts is present."""
    from heypeer.nemotron.client import SYSTEM_PROMPT

    assert "never repeat an action that\nappears there" in SYSTEM_PROMPT
    assert "Only the newest turn can request an action" in SYSTEM_PROMPT


def test_the_prompt_forbids_inventing_facts_it_cannot_check() -> None:
    """Also found live: "quelle heure il est" came back as "Il est 14h",
    invented - the model has no clock, and a made-up answer is
    indistinguishable to the user from a real one. Now it says it cannot
    check."""
    from heypeer.nemotron.client import SYSTEM_PROMPT

    # Reworded in round 36 (the model can now genuinely see the screen via
    # "read_screen", so "you cannot see the screen" became actively wrong) -
    # checking the surviving, still-true half of the same instruction:
    # Hey Peer still has no clock or calendar, and still must not invent one.
    assert "You do not know the current time" in SYSTEM_PROMPT
    assert "Making one up is worse than saying so" in SYSTEM_PROMPT


def test_the_prompt_does_not_still_tell_the_model_it_cannot_see_the_web() -> None:
    """Regression test for a stale instruction, which is the failure mode a
    growing prompt has.

    Before `search_web` existed, the prompt listed the weather and the web
    among the things Hey Peer cannot check and told the model to say so.
    Adding the action did not remove that, so the two contradicted each other
    and the older, more specific line won: "Quelle est la meteo a Paris ?"
    was answered "je n'ai pas acces a cette information" by an assistant that
    could have opened a browser.
    """
    from heypeer.nemotron.client import SYSTEM_PROMPT

    prompt = " ".join(SYSTEM_PROMPT.split())
    # rindex: the phrase also appears as a forward reference higher up.
    refusal = prompt[prompt.rindex("Never invent a fact") : prompt.index("But not knowing")]
    for reachable in ("weather", "web", "news"):
        assert reachable not in refusal.lower(), (
            f"the prompt still tells the model it cannot check the {reachable}"
        )


def test_nothing_hey_peer_can_do_is_listed_as_something_it_cannot() -> None:
    """The general form of the bug above, and how it was actually found.

    "Things you cannot do yet" still named "open an application" and "search
    the web" - both shipped in the two preceding rounds. A prompt that grows
    by appending describes each new capability twice: once as supported, and
    once, further down, as refused. The older line is more specific, so it
    tends to win - which is exactly how "quelle est la meteo" came back as
    "je n'ai pas acces a cette information".
    """
    from heypeer.nemotron.client import SYSTEM_PROMPT
    from heypeer.nemotron.intent import ACTION_DESCRIPTIONS

    prompt = " ".join(SYSTEM_PROMPT.split())
    section = prompt[
        prompt.index("Things you cannot do yet") : prompt.rindex("Never invent a fact")
    ].lower()
    # Driven by ACTION_DESCRIPTIONS rather than a phrase list copied here by
    # hand, so a future action missing this check is a missing dict entry,
    # not a human forgetting to update a second list that only this test
    # reads.
    for action, described in ACTION_DESCRIPTIONS.items():
        assert described not in section, (
            f"the prompt refuses {described!r} ({action!r}), which Hey Peer does"
        )


def test_nothing_hey_peer_can_do_is_listed_as_something_it_cannot_by_keyword() -> None:
    """The exact-phrase check above missed a real instance: round 35 added
    adjust_volume, and the "cannot do yet" list still said "control the
    volume" - different wording for the same refusal ("change the volume"
    is what ACTION_DESCRIPTIONS actually says), so the substring check above
    never fired. The prompt still routed "baisse le son" to reply-and-
    decline until this was found and fixed by hand.

    A single keyword per capability, checked the same way, catches a
    reworded refusal the exact-phrase check cannot. Deliberately not every
    action - a keyword like "file" or "app" would false-positive constantly
    in ordinary prose - only the ones that have *actually* drifted this way
    at least once, so this list grows from real incidents, not speculation.
    """
    from heypeer.nemotron.client import SYSTEM_PROMPT

    prompt = " ".join(SYSTEM_PROMPT.split())
    section = prompt[
        prompt.index("Things you cannot do yet") : prompt.rindex("Never invent a fact")
    ].lower()
    for keyword in ("volume", "screen", "brightness", "clipboard"):
        assert keyword not in section, f"the prompt still mentions {keyword!r} as unsupported"


def test_the_prompt_routes_unknown_facts_to_a_search_rather_than_a_refusal() -> None:
    from heypeer.nemotron.client import SYSTEM_PROMPT

    # Whitespace-normalised: these are sentences in a wrapped paragraph, and
    # asserting on where the line breaks fall makes the test fail every time
    # the paragraph is re-wrapped without its meaning changing.
    prompt = " ".join(SYSTEM_PROMPT.split())

    assert '"search_web"' in prompt
    assert "Do not refuse it." in prompt
    # And the two distinctions that keep it from searching for everything:
    # what only this machine knows, and what the model already knows.
    assert "the current time" in prompt
    assert "combien font deux et deux" in prompt


def test_the_prompt_forbids_promising_an_answer_a_browser_has_to_keep() -> None:
    """`search_web` opens a browser; it tells the user nothing. The model's
    first draft said "Voici la meteo a Paris", which is a claim the action
    does not deliver."""
    from heypeer.nemotron.client import SYSTEM_PROMPT

    assert "promise the browser has to keep" in " ".join(SYSTEM_PROMPT.split())


# --- summarize_for_speech (round 35: clipboard read/summarize) -------------


def _settings() -> Settings:
    return Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://api.studio.nebius.ai/v1",
        nemotron_model_id="nvidia/nemotron-3-nano-omni",
    )


def test_summarize_for_speech_returns_the_summary() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"summary": "Une facture de 42 euros pour mars."}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        summary = client.summarize_for_speech("Facture #1234, montant: 42 EUR, mars 2026")

    assert summary == "Une facture de 42 euros pour mars."


def test_summarize_for_speech_uses_the_dedicated_prompt_not_the_classifier_one() -> None:
    """A different, narrower prompt from SYSTEM_PROMPT - this call never
    needs to choose an action, only describe text that's already known to
    be a clipboard read."""
    from heypeer.nemotron.client import SUMMARIZE_SYSTEM_PROMPT

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"summary": "x"})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        client.summarize_for_speech("some text")

    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    assert messages[0]["content"] == SUMMARIZE_SYSTEM_PROMPT


def test_summarize_for_speech_passes_the_language_along() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"summary": "x"})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        client.summarize_for_speech("some text", language="en")

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "English" in user_message


def test_summarize_for_speech_truncates_a_long_clipboard_capture() -> None:
    """Someone copying an entire document must not turn three spoken
    sentences into a slow, expensive request over the whole thing."""
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"summary": "x"})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        client.summarize_for_speech("a" * 50000)

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert len(user_message) < 4500


def test_summarize_for_speech_returns_empty_string_on_no_answer() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_client.chat.completions.create.return_value = response
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        summary = client.summarize_for_speech("some text")

    assert summary == ""


def test_summarize_for_speech_returns_empty_string_on_bad_json() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="not json"))]
        mock_client.chat.completions.create.return_value = response
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        summary = client.summarize_for_speech("some text")

    assert summary == ""


# --- describe_image (round 36: read_screen) ---------------------------------


def test_describe_image_returns_the_answer() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"answer": "Il y a un message d'erreur 404."}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        answer = client.describe_image(b"fake-png-bytes", "qu'est-ce qu'il y a sur mon ecran ?")

    assert answer == "Il y a un message d'erreur 404."


def test_describe_image_sends_the_image_as_image_url_content() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"answer": "x"})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        client.describe_image(b"fake-png-bytes", "what is this?")

    content = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    types = [part["type"] for part in content]
    assert types == ["text", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_describe_image_passes_the_users_own_question_through() -> None:
    """A specific question gets a specific answer, not a generic
    description of the whole screen - the question is the user's own
    instruction text, forwarded as-is."""
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"answer": "x"})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        client.describe_image(b"fake-png-bytes", "y a-t-il un message d'erreur ?")

    content = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "y a-t-il un message d'erreur ?" in content[0]["text"]


def test_describe_image_returns_empty_string_on_no_answer() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_client.chat.completions.create.return_value = response
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        answer = client.describe_image(b"fake-png-bytes", "what is this?")

    assert answer == ""


# --- diagnose_code (round 37: analyze_code) ---------------------------------


def test_diagnose_code_returns_the_diagnosis() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"diagnosis": "La division par zero se produit si la liste est vide."}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        diagnosis = client.diagnose_code("def f(x): return 1/x", "pourquoi ca plante ?")

    assert diagnosis == "La division par zero se produit si la liste est vide."


def test_diagnose_code_uses_its_own_dedicated_prompt() -> None:
    from heypeer.nemotron.client import DIAGNOSE_CODE_SYSTEM_PROMPT

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"diagnosis": "x"})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        client.diagnose_code("some code", "why?")

    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    assert messages[0]["content"] == DIAGNOSE_CODE_SYSTEM_PROMPT


def test_diagnose_code_passes_the_users_question_through() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response({"diagnosis": "x"})
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        client.diagnose_code("some code", "pourquoi ca plante sur une liste vide ?")

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "pourquoi ca plante sur une liste vide ?" in user_message


def test_diagnose_code_returns_empty_string_on_no_answer() -> None:
    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_client.chat.completions.create.return_value = response
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(_settings())
        diagnosis = client.diagnose_code("some code", "why?")

    assert diagnosis == ""


# --- memory injection (round 38: persistent memory) -------------------------


def test_interpret_text_includes_memory_in_context() -> None:
    settings = _settings()

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "reply", "speech": "x"}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        client.interpret_text(
            "comment je prefere qu'on m'appelle ?",
            skill_context=[],
            memory=["Tom prefere qu'on l'appelle Tom, pas Thomas."],
        )

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Tom prefere qu'on l'appelle Tom, pas Thomas." in user_message


def test_interpret_text_omits_memory_entirely_when_there_is_none() -> None:
    """Matches watched_files/watched_folders' own convention: nothing
    remembered yet should not print an empty list into every prompt."""
    settings = _settings()

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "reply", "speech": "x"}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        client.interpret_text("comment ca va ?", skill_context=[])

    user_message = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "remember" not in user_message.lower()


def test_interpret_text_parses_the_content_field() -> None:
    """remember_fact and general_task carry their payload in "content",
    a separate field from "query" (a search string is not the same shape
    of text as a fact to remember or a task to hand off)."""
    settings = _settings()

    with patch("heypeer.nemotron.client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_response(
            {"action": "remember_fact", "content": "Le projet doit etre livre vendredi"}
        )
        mock_openai_cls.return_value = mock_client

        client = NemotronClient(settings)
        intent = client.interpret_text("retiens que...", skill_context=[])

    assert intent.action == "remember_fact"
    assert intent.content == "Le projet doit etre livre vendredi"


def test_the_prompt_says_tu_never_vous_in_french() -> None:
    """Found live: reading a stored memory fact back ("tu preferes..." vs
    "vous preferez...") drifted to the formal register roughly two thirds
    of the time before this rule was added explicitly - a stored fact reads
    like a neutral, third-person note, which pulled the model that way."""
    from heypeer.nemotron.client import SYSTEM_PROMPT

    prompt = " ".join(SYSTEM_PROMPT.split())
    assert '"tu", never "vous"' in prompt


def test_the_prompt_routes_website_interaction_to_general_task_not_open_app() -> None:
    """Found live: "ouvre YouTube et joue la derniere video de Squeezie" and
    "va sur Amazon et ajoute des piles AA au panier" both went to
    "open_app" - matching "ouvre"/"va sur" against open_app's own trigger
    words even though the target is a website with a task attached, not a
    desktop application. open_app would try to launch "YouTube" as an app
    (it isn't one) and silently drop the rest of the instruction. Fixed by
    naming the exact failing cases as general_task examples and stating
    explicitly that open_app is only for a real desktop application."""
    from heypeer.nemotron.client import SYSTEM_PROMPT

    prompt = " ".join(SYSTEM_PROMPT.split())
    assert "va sur Amazon et ajoute des piles AA au panier" in prompt
    assert "not a website or an online service" in prompt
