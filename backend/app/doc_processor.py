import traceback

from sqlalchemy.orm import Session

from . import models, vector_store

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

# File extensions treated as plain text (no PDF parser needed).
PLAINTEXT_EXTENSIONS = {
    ".txt", ".log", ".csv", ".tsv", ".json", ".xml",
    ".yaml", ".yml", ".md", ".ndjson",
}


def _chunk_text(text: str) -> list[dict]:
    """
    Sliding-window chunker over raw text: CHUNK_SIZE-character windows
    with CHUNK_OVERLAP characters of overlap between consecutive chunks.
    Empty (whitespace-only) chunks are dropped.
    """
    chunks = []
    start = 0
    index = 0
    length = len(text)
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)

    while start < length:
        chunk_str = text[start:start + CHUNK_SIZE]
        if chunk_str.strip():
            chunks.append({"text": chunk_str, "chunk_index": index})
            index += 1
        start += step

    return chunks


def _extract_text(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Return (full_text, page_count).
    - Plain-text files: decoded as UTF-8 (with fallback to latin-1). page_count = 1.
    - PDFs: extracted with PyMuPDF; page_count = number of PDF pages.
    """
    from pathlib import Path
    ext = Path(filename).suffix.lower()

    if ext in PLAINTEXT_EXTENSIONS:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")
        return text, 1

    # Default: treat as PDF.
    import fitz
    pdf = fitz.open(stream=file_bytes, filetype="pdf")
    pages = [page.get_text() for page in pdf]
    return "\n".join(pages), len(pages)


def process_document_task(document_id: int, file_bytes: bytes, db: Session) -> None:
    """
    Extracts text from an uploaded file's raw bytes (PDF or plain text),
    chunks it, persists the chunks as DocumentChunk rows, and embeds them
    into the shared FAISS vector_store so the RAG chat can answer questions
    about the document. Runs in the background after the upload response has
    already been sent.
    """
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        db.close()
        return

    try:
        document.status = "processing"
        db.commit()

        full_text, page_count = _extract_text(file_bytes, document.filename)
        document.page_count = page_count

        chunks = _chunk_text(full_text)

        if chunks:
            mappings = [
                {"document_id": document_id, "chunk_index": c["chunk_index"], "text": c["text"]}
                for c in chunks
            ]
            db.bulk_insert_mappings(models.DocumentChunk, mappings, return_defaults=True)

            vecs_input = [{"text": m["text"], "entry_ids": [m["id"]]} for m in mappings]
            vector_store.add_chunks(vecs_input, user_id=document.uploaded_by, file_id=document_id, kind="document")
            vector_store.save()

        document.status = "completed"
        db.commit()
    except Exception:
        print(f"Failed to process document {document_id}:")
        traceback.print_exc()
        db.rollback()
        document.status = "failed"
        db.commit()
    finally:
        db.close()

