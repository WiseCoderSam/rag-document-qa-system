import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .database import SessionLocal
from .processor import process_log_file_task
from . import models

WATCH_DIR = Path(__file__).resolve().parent.parent / "ingestion_watch"


class LogFileEventHandler(FileSystemEventHandler):
    """
    Reacts to new .log files dropped into a per-user subfolder of the
    ingestion watch directory (WATCH_DIR/<user_id>/*.log).

    Files must live one level below WATCH_DIR so the owning user_id can be
    read from the parent folder name. Every read endpoint in main.py filters
    on LogFile.uploaded_by == current_user.id, so a file with no real owner
    would be ingested but permanently invisible in the UI — the per-folder
    convention is what makes drop-folder ingestion actually usable end to
    end, rather than a backend-only feature.
    """

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix != ".log":
            return

        if path.parent == WATCH_DIR or path.parent.parent != WATCH_DIR:
            print(
                f"[watcher] Ignoring {path} — drop .log files into "
                f"{WATCH_DIR}/<your-user-id>/, not directly into {WATCH_DIR} "
                "(there'd be no user to attribute the file to)."
            )
            return

        user_id = path.parent.name

        # Process off the watchdog dispatch thread so we keep watching for new files.
        threading.Thread(target=_ingest_log_file, args=(path, user_id), daemon=True).start()


def _ingest_log_file(path: Path, user_id: str) -> None:
    db = SessionLocal()
    try:
        log_file = models.LogFile(
            filename=path.name,
            file_url=str(path.resolve()),
            status="processing",
            uploaded_by=user_id,
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
    """Creates the watch directory (if needed) and starts watching it (and its per-user subfolders) in the background."""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(LogFileEventHandler(), str(WATCH_DIR), recursive=True)
    observer.start()
    print(f"Log ingestion watcher started on {WATCH_DIR} (drop files into {WATCH_DIR}/<user-id>/)")
    return observer


def stop_watcher(observer: Observer) -> None:
    observer.stop()
    observer.join()
    print("Log ingestion watcher stopped")
