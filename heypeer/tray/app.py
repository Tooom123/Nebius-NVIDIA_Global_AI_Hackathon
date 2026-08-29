"""System tray icon: shows Hey Peer's status and exposes the "auto mode" toggle.

`TrayApp.run()` blocks the calling thread with the tray event loop — on some
platforms (notably macOS) that loop wants the *main* thread. The convention
used by `heypeer/main.py` is: start the rest of the pipeline (watchers,
wake-word listener) in a background thread, then call `TrayApp.run()` on the
main thread last.
"""

from collections.abc import Callable
from enum import Enum

import pystray

from heypeer.tray.icon_images import make_icon_image


class Status(str, Enum):
    OFF = "off"
    LISTENING = "listening"
    EXECUTING = "executing"
    ERROR = "error"


STATUS_LABELS: dict[Status, str] = {
    # Plain ASCII hyphen, not an em dash: some tray backends (X11's WM_NAME)
    # encode the icon title as Latin-1, which can't represent U+2014.
    Status.OFF: "Hey Peer - en pause",
    Status.LISTENING: "Hey Peer - actif, à l'écoute",
    Status.EXECUTING: "Hey Peer - exécution en cours",
    Status.ERROR: "Hey Peer - erreur",
}


class TrayApp:
    def __init__(
        self,
        on_auto_mode_change: Callable[[bool], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_prompt: Callable[[str], None] | None = None,
    ) -> None:
        self.status = Status.OFF
        self.auto_mode = False
        self._on_auto_mode_change = on_auto_mode_change
        self._on_quit = on_quit
        self._on_prompt = on_prompt
        self.icon = pystray.Icon(
            "hey_peer",
            icon=make_icon_image(Status.OFF.value),
            title=STATUS_LABELS[Status.OFF],
            menu=pystray.Menu(
                pystray.MenuItem(lambda _item: STATUS_LABELS[self.status], None, enabled=False),
                pystray.MenuItem(
                    "Mode auto", self._toggle_auto_mode, checked=lambda _item: self.auto_mode
                ),
                pystray.MenuItem("Demander à Hey Peer...", self._prompt),
                pystray.MenuItem("Quitter", self._quit),
            ),
        )

    def _toggle_auto_mode(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.set_auto_mode(not self.auto_mode)

    def _prompt(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        if self._on_prompt is None:
            return
        from heypeer.tray.prompt import ask_instruction

        text = ask_instruction()
        if text:
            self._on_prompt(text)

    def _quit(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        if self._on_quit is not None:
            self._on_quit()
        self.icon.stop()

    def set_auto_mode(self, enabled: bool) -> None:
        self.auto_mode = enabled
        self.set_status(Status.LISTENING if enabled else Status.OFF)
        if self._on_auto_mode_change is not None:
            self._on_auto_mode_change(enabled)

    def set_status(self, status: Status) -> None:
        self.status = status
        self.icon.icon = make_icon_image(status.value)
        self.icon.title = STATUS_LABELS[status]
        self.icon.update_menu()

    def run(self) -> None:
        self.icon.run()

    def stop(self) -> None:
        self.icon.stop()
