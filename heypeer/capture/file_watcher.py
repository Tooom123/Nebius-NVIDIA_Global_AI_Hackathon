"""Watches a directory for file move/rename events.

Used for the file-sorting demo scenario: watching e.g. ~/Downloads directly
tells us which file moved where via the OS's own file-system events, rather
than inferring it from blind click coordinates. This makes replay (see
`heypeer/executor/runner.py`) robust to the file manager window being in a
different position or state than when the pattern was first observed.
"""

from collections.abc import Callable
from pathlib import Path

from heypeer.capture.events import ActionEvent, ActionType

EventSink = Callable[[ActionEvent], None]


class FileOpWatcher:
    """Emits a FILE_MOVE ActionEvent whenever a file is moved or renamed
    within `watch_dir` (non-recursive by default — enough for one demo
    scenario like sorting files out of a downloads folder)."""

    def __init__(self, watch_dir: Path, on_event: EventSink, recursive: bool = False) -> None:
        self.watch_dir = watch_dir
        self._on_event = on_event
        self._recursive = recursive
        self._observer = None

    def start(self) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_moved(self, event) -> None:
                if event.is_directory:
                    return
                watcher._on_event(
                    ActionEvent(
                        type=ActionType.FILE_MOVE,
                        app_name="",
                        window_title=str(Path(event.dest_path).parent),
                        src_path=str(event.src_path),
                        dest_path=str(event.dest_path),
                    )
                )

        self._observer = Observer()
        self._observer.schedule(Handler(), str(self.watch_dir), recursive=self._recursive)
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
