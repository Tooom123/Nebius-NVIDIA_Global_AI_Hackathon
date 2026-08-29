from unittest.mock import MagicMock

from heypeer.tray.app import Status, TrayApp


def test_starts_off() -> None:
    app = TrayApp()
    assert app.status == Status.OFF
    assert app.auto_mode is False


def test_toggle_auto_mode_calls_callback_and_updates_status() -> None:
    on_change = MagicMock()
    app = TrayApp(on_auto_mode_change=on_change)

    app._toggle_auto_mode(app.icon, None)

    assert app.auto_mode is True
    assert app.status == Status.LISTENING
    on_change.assert_called_once_with(True)

    app._toggle_auto_mode(app.icon, None)

    assert app.auto_mode is False
    assert app.status == Status.OFF
    on_change.assert_called_with(False)


def test_set_status_updates_icon_and_title() -> None:
    app = TrayApp()
    app.set_status(Status.EXECUTING)

    assert app.icon.title == "Hey Peer - exécution en cours"
    assert app.icon.icon.getpixel((32, 32))[:3] == (52, 152, 219)


def test_quit_calls_callback_and_stops_icon() -> None:
    on_quit = MagicMock()
    app = TrayApp(on_quit=on_quit)
    app.icon.stop = MagicMock()

    app._quit(app.icon, None)

    on_quit.assert_called_once()
    app.icon.stop.assert_called_once()


def test_menu_reflects_current_state() -> None:
    app = TrayApp()
    status_item, toggle_item, prompt_item, quit_item = list(app.icon.menu)

    assert status_item.text == "Hey Peer - en pause"
    assert toggle_item.checked is False
    assert prompt_item.text == "Demander à Hey Peer..."

    app.set_auto_mode(True)
    assert toggle_item.checked is True
    assert status_item.text == "Hey Peer - actif, à l'écoute"


def test_prompt_calls_on_prompt_with_typed_text(monkeypatch) -> None:
    on_prompt = MagicMock()
    app = TrayApp(on_prompt=on_prompt)
    monkeypatch.setattr("heypeer.tray.prompt.ask_instruction", lambda: "déplace X vers Y")

    app._prompt(app.icon, None)

    on_prompt.assert_called_once_with("déplace X vers Y")


def test_prompt_ignores_empty_result(monkeypatch) -> None:
    on_prompt = MagicMock()
    app = TrayApp(on_prompt=on_prompt)
    monkeypatch.setattr("heypeer.tray.prompt.ask_instruction", lambda: None)

    app._prompt(app.icon, None)

    on_prompt.assert_not_called()
