from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from . import models
from .parser import parse_log_line
from .rules import run_detection_rules


def _fetch_log_content(file_url: str) -> bytes:
    """
    Retrieves raw log file bytes from either a Supabase Storage public URL
    or a local filesystem path (the local_storage/ fallback).
    """
    if file_url.startswith("http://") or file_url.startswith("https://"):
        response = httpx.get(file_url, timeout=30)
        response.raise_for_status()
        return response.content

    return Path(file_url).read_bytes()


def process_log_file_task(file_id: int, db: Session) -> None:
    """
    Fetches an uploaded log file's contents, parses each line into a
    normalized LogEntry, and bulk inserts them into the database. Runs in
    the background after the upload response has already been sent.
    """
    log_file = db.query(models.LogFile).filter(models.LogFile.id == file_id).first()
    if not log_file:
        db.close()
        return

    try:
        content = _fetch_log_content(log_file.file_url)
        text = content.decode("utf-8", errors="replace")

        entries = []
        for line in text.splitlines():
            if not line.strip():
                continue
            parsed = parse_log_line(line)
            parsed["file_id"] = log_file.id
            entries.append(parsed)

        if entries:
            db.bulk_insert_mappings(models.LogEntry, entries)

            # Transient (unpersisted) objects are enough for rule evaluation -
            # they only need attribute access, not identity in the session.
            entry_objects = [models.LogEntry(**e) for e in entries]
            run_detection_rules(db, entry_objects, log_file)

        log_file.status = "completed"
        db.commit()
    except Exception as e:
        print(f"Failed to process log file {file_id}: {e}")
        db.rollback()
        log_file.status = "failed"
        db.commit()
    finally:
        db.close()
