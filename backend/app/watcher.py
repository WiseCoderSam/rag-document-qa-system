import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .database import SessionLocal
from .processor import process_log_file_task
from . import models

WATCH_DIR = Path(__file__).resolve().parent.parent / "ingestion_watch"


class LogFileEventHandler(FileSystemEventHandler):
    """Reacts to new .log files dropped into the ingestion watch directory."""

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix != ".log":
            return

        # Process off the watchdog dispatch thread so we keep watching for new files.
        threading.Thread(target=_ingest_log_file, args=(path,), daemon=True).start()


def _ingest_log_file(path: Path) -> None:
    db = SessionLocal()
    try:
        log_file = models.LogFile(
            filename=path.name,
            file_url=str(path.resolve()),
            status="processing",
            uploaded_by="system_watcher",
        )
        db.add(log_file)
        db.commit()
        db.refresh(log_file)
        file_id = log_file.id
    finally:
        db.close()

    # process_log_file_task owns and closes the session it's given.
    process_log_file_task(file_id, SessionLocal())


def start_watcher() -> Observer:
    """Creates the watch directory (if needed) and starts watching it in the background."""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(LogFileEventHandler(), str(WATCH_DIR), recursive=False)
    observer.start()
    print(f"Log ingestion watcher started on {WATCH_DIR}")
    return observer


def stop_watcher(observer: Observer) -> None:
    observer.stop()
    observer.join()
    print("Log ingestion watcher stopped")
