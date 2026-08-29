import time
from pathlib import Path

from heypeer.capture.events import ActionType
from heypeer.capture.file_watcher import FileOpWatcher


def test_detects_a_real_file_move(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    src = watch_dir / "a.pdf"
    src.write_text("x")

    events = []
    watcher = FileOpWatcher(watch_dir, on_event=events.append)
    watcher.start()
    try:
        dest = watch_dir / "b.pdf"
        src.rename(dest)

        deadline = time.time() + 5
        while not events and time.time() < deadline:
            time.sleep(0.1)
    finally:
        watcher.stop()

    assert len(events) == 1
    assert events[0].type == ActionType.FILE_MOVE
    assert events[0].src_path == str(src)
    assert events[0].dest_path == str(dest)


def test_start_on_missing_directory_does_not_raise(tmp_path: Path, capsys) -> None:
    missing_dir = tmp_path / "does_not_exist"
    watcher = FileOpWatcher(missing_dir, on_event=lambda _e: None)

    watcher.start()  # must not raise

    assert watcher._observer is None
    assert "introuvable" in capsys.readouterr().out
    watcher.stop()  # must also be a no-op, not raise
