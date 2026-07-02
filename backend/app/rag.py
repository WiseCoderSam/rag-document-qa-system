"""
RAG retrieval for the investigation chat feature (prd.md: "RAG-powered
investigation chat", "Chat with previous incidents").

Turns a user's question into a user-scoped vector_store.search() call (see
app.vector_store — Task 2's per-user isolation) and assembles a
source-cited context string for app.ai.generate_chat_response().
"""

from sqlalchemy.orm import Session

from . import models, vector_store


class IncidentNotFoundError(Exception):
    """Raised when incident_id doesn't exist, or doesn't belong to the caller."""


def _entry_to_context_line(index: int, entry: "models.LogEntry") -> str:
    ts   = entry.timestamp.isoformat() if entry.timestamp else "N/A"
    host = entry.hostname or "unknown-host"
    sev  = entry.severity or "INFO"
    msg  = (entry.message or "").strip()
    return f"[{index}] id={entry.id} | {ts} | {host} | {sev} | {msg}"


def retrieve_context(
    db: Session,
    question: str,
    user_id: str,
    file_id: int | None = None,
    incident_id: int | None = None,
    k: int = 5,
) -> tuple[str, list[int]]:
    """
    Resolve retrieval scope, run a user-scoped vector_store.search(), and
    assemble a context string that retains enough detail per log line
    (entry id, timestamp, hostname) for the LLM's answer to be cited back
    to specific log entries.

    If *incident_id* is given, it's resolved to its LogFile and retrieval
    is scoped to that file (*file_id* is ignored in that case). An
    incident_id that doesn't exist, or belongs to a log file uploaded by a
    different user, raises IncidentNotFoundError — both cases are
    indistinguishable to the caller so this endpoint can't be used to
    probe which incident ids exist for other users.

    Returns (context, source_ids). Both are empty when nothing matches —
    callers should treat that as "no matching log data found" rather than
    invoking the LLM with empty context.
    """
    scoped_file_id = file_id

    if incident_id is not None:
        incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
        if incident is None or incident.log_file is None or incident.log_file.uploaded_by != user_id:
            raise IncidentNotFoundError(f"Incident {incident_id} not found.")
        scoped_file_id = incident.log_file_id

    source_ids = vector_store.search(question, user_id, k=k, file_id=scoped_file_id)
    if not source_ids:
        return "", []

    entries_by_id = {
        entry.id: entry
        for entry in db.query(models.LogEntry).filter(models.LogEntry.id.in_(source_ids)).all()
    }
    # Preserve vector_store's relevance ranking rather than the DB's fetch order.
    ordered_entries = [entries_by_id[i] for i in source_ids if i in entries_by_id]

    context = "\n".join(
        _entry_to_context_line(i, entry) for i, entry in enumerate(ordered_entries, start=1)
    )
    return context, [entry.id for entry in ordered_entries]
