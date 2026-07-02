from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from . import models, summarizer, vector_store
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
            # return_defaults=True populates each dict's generated "id" back
            # after insert — without it every entry stays id=None below, so
            # chunk_entries()/vector_store can never attribute a chunk match
            # back to a real LogEntry row (RAG query source_ids would all be
            # NULL and match nothing).
            db.bulk_insert_mappings(models.LogEntry, entries, return_defaults=True)

            # Transient (unpersisted) objects are enough for rule evaluation
            # and embedding — they only need attribute access, not DB identity.
            entry_objects = [models.LogEntry(**e) for e in entries]
            incidents = run_detection_rules(db, entry_objects, log_file)

            # AI incident summaries (prd.md feature #6). A summarization
            # failure for one incident must not fail the whole ingestion —
            # log it and leave that incident's summary null, same as the
            # outer except below leaves log_file.status="failed" rather
            # than raising.
            for incident in incidents:
                try:
                    incident.summary = summarizer.summarize_incident(db, incident)
                except Exception as e:
                    print(f"Failed to summarize incident ({incident.rule_name}) for file {log_file.id}: {e}")

            # Build / update the FAISS index for RAG queries. add_entries()
            # chunks internally (app.chunking), so this stays a handful of
            # Gemini embedding calls per file instead of one per log line.
            # user_id/file_id tag every vector so search() can enforce
            # per-user data isolation (see vector_store.search).
            vector_store.add_entries(entry_objects, user_id=log_file.uploaded_by, file_id=log_file.id)
            vector_store.save()

        log_file.status = "completed"
        db.commit()
    except Exception as e:
        print(f"Failed to process log file {file_id}: {e}")
        db.rollback()
        log_file.status = "failed"
        db.commit()
    finally:
        db.close()
