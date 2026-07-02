"""
Singleton FAISS vector store for log entry AND document chunk embeddings.
Both share one flat index; every vector is tagged with a *kind* ("log" or
"document") alongside user_id/file_id.

Each FAISS vector corresponds to a *chunk* (a window of log lines, or a
slice of an uploaded document) produced by app.chunking / app.doc_processor,
tagged with the owning user_id, file_id, and kind. IndexFlatIP has no native
metadata filtering, so search() oversamples from the flat index and filters
by user_id/file_id/kind in Python — this is what enforces per-user data
isolation, since without it any authenticated user's query could retrieve
any other user's log lines or documents.

`file_id` is only unique *within* a kind: LogFile.id and Document.id are
independent autoincrement sequences in separate tables, so a LogFile and a
Document can legitimately share the same numeric id. Callers that scope a
search to a specific file MUST also pass `kind`, or two unrelated files
(one a log, one a document) with the same id will bleed into each other's
results.

Public API
----------
add_chunks(chunks, user_id, file_id, kind) — embed a list of chunk dicts and insert into the index
add_entries(entries, user_id, file_id) — convenience: chunk then embed raw LogEntry objects (kind="log")
search(query, user_id, k, file_id, kind) — embed query and return matching {"id", "kind"} dicts owned by user_id
save() / load()     — persist index and metadata to disk
_reset()            — test-only: clear all in-memory state
"""

import json
import threading
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_DIM  = 768
_INDEX = None  # faiss.IndexFlatIP — lazily imported

# position i in the FAISS index → {"entry_ids": list[int], "user_id": str, "file_id": int}
_METADATA: list[dict] = []

_STORE_DIR  = Path(__file__).resolve().parent.parent / "vector_store"
_INDEX_PATH = _STORE_DIR / "index.faiss"
_MAP_PATH   = _STORE_DIR / "id_map.json"


def _get_faiss():
    import faiss
    return faiss


def _ensure_index():
    global _INDEX
    if _INDEX is None:
        faiss = _get_faiss()
        _INDEX = faiss.IndexFlatIP(_DIM)
    return _INDEX


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_chunks(chunks: list[dict], user_id: str, file_id: int, kind: str = "log") -> None:
    """
    Embed each chunk's ``text`` (via ``ai.get_embeddings``) and add to the
    index, tagging every resulting vector with *user_id*, *file_id*, and
    *kind* so ``search()`` can later restrict matches to their owner (and,
    when scoped, to the right file of the right kind).

    Parameters
    ----------
    chunks:
        Output of ``app.chunking.chunk_entries`` (or the equivalent shape
        from ``app.doc_processor``) — each dict has
        ``{"text": str, "entry_ids": list[int]}``.
    user_id:
        Owning user's id (``LogFile.uploaded_by`` / ``Document.uploaded_by``)
        — required so a caller can never retrieve another user's data via
        search().
    file_id:
        The source row's id — ``LogFile.id`` when kind="log",
        ``Document.id`` when kind="document". These are independent
        autoincrement sequences in separate tables and can collide, which
        is exactly why *kind* must be stored and filtered on too.
    kind:
        Either "log" (chunk['entry_ids'] are LogEntry ids) or "document"
        (chunk['entry_ids'] are DocumentChunk ids).
    """
    if not chunks:
        return

    from .ai import get_embeddings  # local import avoids circular deps

    texts = [c["text"] for c in chunks]
    vecs  = get_embeddings(texts)

    valid_vecs = []
    valid_meta = []
    for vec, chunk in zip(vecs, chunks):
        if not chunk["entry_ids"]:
            continue
        valid_vecs.append(vec)
        valid_meta.append({
            "entry_ids": chunk["entry_ids"],
            "user_id": user_id,
            "file_id": file_id,
            "kind": kind,
        })

    if not valid_vecs:
        return

    matrix = np.array(valid_vecs, dtype=np.float32)

    with _LOCK:
        idx = _ensure_index()
        idx.add(matrix)
        _METADATA.extend(valid_meta)

    print(f"[vector_store] Added {len(valid_vecs)} {kind} chunk vectors for user={user_id} file={file_id} (total: {_ensure_index().ntotal})")


def add_entries(entries: list, user_id: str, file_id: int) -> None:
    """
    Convenience wrapper: chunk *entries* then call add_chunks(), tagging the
    resulting vectors with *user_id*, *file_id*, and kind="log".
    Uses app.chunking defaults (CHUNK_SIZE=10, CHUNK_OVERLAP=2).
    """
    from .chunking import chunk_entries
    add_chunks(chunk_entries(entries), user_id=user_id, file_id=file_id, kind="log")


def search(
    query: str,
    user_id: str,
    k: int = 5,
    file_id: int | None = None,
    kind: str | None = None,
) -> list[dict]:
    """
    Embed *query* and return the top-k matching chunks that belong to
    *user_id* (and, if given, *file_id* + *kind*), as a ranked list of
    ``{"id": int, "kind": "log" | "document"}`` dicts — *id* is a LogEntry
    id when kind="log", a DocumentChunk id when kind="document".

    *file_id* is only meaningful combined with *kind*, since LogFile.id and
    Document.id are independent sequences that can collide (see module
    docstring); passing *file_id* without *kind* would silently mix a log
    file's chunks with an unrelated same-numbered document's chunks.

    IndexFlatIP has no native per-vector metadata filtering, so this
    searches the *entire* flat index (cheap — IndexFlatIP is already an
    exhaustive linear scan, so requesting all ntotal results costs the same
    as requesting a handful) and then filters by user_id/file_id/kind in
    ranked order, stopping once k matching chunks have been collected.
    Returns [] when the index is empty or the user has no matching vectors.
    """
    from .ai import get_embedding

    with _LOCK:
        idx = _ensure_index()
        if idx.ntotal == 0:
            return []

        vec = np.array([get_embedding(query)], dtype=np.float32)
        _scores, positions = idx.search(vec, idx.ntotal)
        metadata_snapshot = _METADATA

    seen: set[tuple[str, int]] = set()
    result: list[dict] = []
    matched_chunks = 0
    for pos in positions[0]:
        if matched_chunks >= k:
            break
        if pos < 0 or pos >= len(metadata_snapshot):
            continue

        meta = metadata_snapshot[pos]
        # Vectors persisted before "kind" existed have no such key — they
        # all predate the document-upload feature, so they're all logs.
        meta_kind = meta.get("kind", "log")

        if meta["user_id"] != user_id:
            continue
        if file_id is not None and meta["file_id"] != file_id:
            continue
        if kind is not None and meta_kind != kind:
            continue

        matched_chunks += 1
        for entry_id in meta["entry_ids"]:
            dedup_key = (meta_kind, entry_id)
            if dedup_key not in seen:
                seen.add(dedup_key)
                result.append({"id": entry_id, "kind": meta_kind})

    return result


def save() -> None:
    """Persist the index and metadata to disk."""
    faiss = _get_faiss()
    _STORE_DIR.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        idx = _ensure_index()
        faiss.write_index(idx, str(_INDEX_PATH))
        _MAP_PATH.write_text(json.dumps(_METADATA), encoding="utf-8")

    print(f"[vector_store] Saved {idx.ntotal} chunk vectors to {_STORE_DIR}")


def load() -> None:
    """Load a previously persisted index and metadata from disk."""
    global _INDEX, _METADATA

    if not _INDEX_PATH.exists() or not _MAP_PATH.exists():
        print("[vector_store] No persisted index found — starting fresh.")
        return

    faiss = _get_faiss()
    with _LOCK:
        _INDEX    = faiss.read_index(str(_INDEX_PATH))
        _METADATA = json.loads(_MAP_PATH.read_text(encoding="utf-8"))

    print(f"[vector_store] Loaded {_INDEX.ntotal} chunk vectors from {_STORE_DIR}")


# ---------------------------------------------------------------------------
# Test helper — NOT for production use
# ---------------------------------------------------------------------------

def _reset() -> None:
    """Reset singleton state. Used only by the pytest test suite."""
    global _INDEX, _METADATA
    with _LOCK:
        _INDEX    = None
        _METADATA = []
