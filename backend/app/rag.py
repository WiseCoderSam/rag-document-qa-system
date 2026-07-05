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


def _chunk_to_context_line(index: int, chunk: "models.DocumentChunk") -> str:
    text = (chunk.text or "").strip()
    return f"[{index}] id={chunk.id} | document_id={chunk.document_id} | chunk #{chunk.chunk_index} | {text}"


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
    assemble a context string that retains enough detail per line (entry
    id, timestamp, hostname for logs; document/chunk index for documents)
    for the LLM's answer to be cited back to specific sources.

    If *incident_id* is given, it's resolved to its LogFile and retrieval
    is scoped to that file (*file_id* is ignored in that case). An
    incident_id that doesn't exist, or belongs to a log file uploaded by a
    different user, raises IncidentNotFoundError — both cases are
    indistinguishable to the caller so this endpoint can't be used to
    probe which incident ids exist for other users.

    If *file_id* is given (and *incident_id* is not), it's checked against
    the caller's own Documents first to decide whether to scope the search
    as kind="document" or kind="log" — LogFile.id and Document.id are
    independent sequences that can collide, so this scope MUST carry a
    kind rather than filtering on the bare id (see vector_store module
    docstring).

    With neither *incident_id* nor *file_id*, retrieval is unscoped and can
    return a ranked mix of both log entries and document chunks — each
    result id is resolved against the right table using the kind
    vector_store tagged it with, so same-numbered ids from the two tables
    are never conflated.

    Returns (context, source_ids). Both are empty when nothing matches —
    callers should treat that as "no matching log data found" rather than
    invoking the LLM with empty context.
    """
    scoped_file_id = file_id
    scoped_kind = None

    if incident_id is not None:
        incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
        if incident is None or incident.log_file is None or incident.log_file.uploaded_by != user_id:
            raise IncidentNotFoundError(f"Incident {incident_id} not found.")
        scoped_file_id = incident.log_file_id
        scoped_kind = "log"
    elif file_id is not None:
        owns_document = (
            db.query(models.Document.id)
            .filter(models.Document.id == file_id, models.Document.uploaded_by == user_id)
            .first()
            is not None
        )
        scoped_kind = "document" if owns_document else "log"

    results = vector_store.search(question, user_id, k=k, file_id=scoped_file_id, kind=scoped_kind)
    if not results:
        return "", []

    log_ids = [r["id"] for r in results if r["kind"] == "log"]
    doc_ids = [r["id"] for r in results if r["kind"] == "document"]

    entries_by_id = {}
    if log_ids:
        entries_by_id = {
            entry.id: entry
            for entry in db.query(models.LogEntry).filter(models.LogEntry.id.in_(log_ids)).all()
        }

    chunks_by_id = {}
    if doc_ids:
        chunks_by_id = {
            chunk.id: chunk
            for chunk in db.query(models.DocumentChunk).filter(models.DocumentChunk.id.in_(doc_ids)).all()
        }

    # Preserve vector_store's relevance ranking rather than the DB's fetch
    # order, resolving each result against the table its own kind points
    # to — never guessing based on the numeric id alone.
    context_lines = []
    ordered_ids = []
    for result in results:
        if result["kind"] == "log" and result["id"] in entries_by_id:
            context_lines.append(_entry_to_context_line(len(ordered_ids) + 1, entries_by_id[result["id"]]))
            ordered_ids.append(result["id"])
        elif result["kind"] == "document" and result["id"] in chunks_by_id:
            context_lines.append(_chunk_to_context_line(len(ordered_ids) + 1, chunks_by_id[result["id"]]))
            ordered_ids.append(result["id"])

    if not ordered_ids:
        return "", []

    return "\n".join(context_lines), ordered_ids
