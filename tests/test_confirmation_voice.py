from heypeer.confirmation.voice import parse_confirmation


def test_parse_confirmation_recognizes_french_yes() -> None:
    assert parse_confirmation("oui") is True
    assert parse_confirmation("Oui, vas-y") is True
    assert parse_confirmation("d'accord") is True


def test_parse_confirmation_recognizes_french_no() -> None:
    assert parse_confirmation("non") is False
    assert parse_confirmation("non, annule") is False
    assert parse_confirmation("stop") is False


def test_parse_confirmation_recognizes_english() -> None:
    assert parse_confirmation("yes") is True
    assert parse_confirmation("yeah go ahead") is True
    assert parse_confirmation("no thanks") is False


def test_parse_confirmation_returns_none_for_unclear_reply() -> None:
    assert parse_confirmation("what do you mean") is None
    assert parse_confirmation("") is None
    assert parse_confirmation("   ") is None
