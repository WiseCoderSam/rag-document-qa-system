"""
RAG retrieval for the document Q&A chat feature.

Turns a user's question into a user-scoped vector_store.search() call (see
app.vector_store's per-user isolation) and assembles a source-cited context
string for app.ai.generate_chat_response().
"""

from sqlalchemy.orm import Session

from . import models, vector_store


class DocumentNotFoundError(Exception):
    """Raised when document_id doesn't exist, or doesn't belong to the caller."""


def _chunk_to_context_line(index: int, chunk: "models.DocumentChunk") -> str:
    text = (chunk.text or "").strip()
    return f"[{index}] id={chunk.id} | document_id={chunk.document_id} | chunk #{chunk.chunk_index} | {text}"


def retrieve_context(
    db: Session,
    question: str,
    user_id: str,
    document_id: int | None = None,
    k: int = 5,
) -> tuple[str, list[int]]:
    """
    Run a user-scoped vector_store.search() over the caller's document
    chunks and assemble a context string that retains enough detail per
    line (chunk id, document id, chunk index) for the LLM's answer to be
    cited back to specific sources.

    If *document_id* is given, it must belong to one of the caller's own
    documents; retrieval is then scoped to that document. A document_id
    that doesn't exist, or belongs to a different user, raises
    DocumentNotFoundError — both cases are indistinguishable to the caller
    so this endpoint can't be used to probe which document ids exist for
    other users.

    The search is always filtered to kind="document": the persisted FAISS
    index may still hold vectors from the retired log-ingestion feature,
    and those must never surface as citations that resolve to nothing.

    Returns (context, source_ids). Both are empty when nothing matches —
    callers should treat that as "no matching content found" rather than
    invoking the LLM with empty context.
    """
    if document_id is not None:
        owns_document = (
            db.query(models.Document.id)
            .filter(models.Document.id == document_id, models.Document.uploaded_by == user_id)
            .first()
            is not None
        )
        if not owns_document:
            raise DocumentNotFoundError(f"Document {document_id} not found.")

    results = vector_store.search(question, user_id, k=k, file_id=document_id, kind="document")
    if not results:
        return "", []

    chunk_ids = [r["id"] for r in results]
    chunks_by_id = {
        chunk.id: chunk
        for chunk in db.query(models.DocumentChunk).filter(models.DocumentChunk.id.in_(chunk_ids)).all()
    }

    # Preserve vector_store's relevance ranking rather than the DB's fetch
    # order; chunk ids whose row no longer exists (deleted document) are
    # silently dropped.
    context_lines = []
    ordered_ids = []
    for result in results:
        if result["id"] in chunks_by_id:
            context_lines.append(_chunk_to_context_line(len(ordered_ids) + 1, chunks_by_id[result["id"]]))
            ordered_ids.append(result["id"])

    if not ordered_ids:
        return "", []

    return "\n".join(context_lines), ordered_ids
