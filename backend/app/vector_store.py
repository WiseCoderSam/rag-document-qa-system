"""
Singleton FAISS vector store for log entry chunk embeddings.

Each FAISS vector corresponds to a *chunk* (a window of log lines) produced
by app.chunking, tagged with the owning user_id and file_id.  IndexFlatIP
has no native metadata filtering, so search() oversamples from the flat
index and filters by user_id/file_id in Python — this is what enforces
per-user data isolation, since without it any authenticated user's query
could retrieve any other user's log lines.

Public API
----------
add_chunks(chunks, user_id, file_id) — embed a list of chunk dicts and insert into the index
add_entries(entries, user_id, file_id) — convenience: chunk then embed raw LogEntry objects
search(query, user_id, k, file_id) — embed query and return flat list of matching LogEntry IDs owned by user_id
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

def add_chunks(chunks: list[dict], user_id: str, file_id: int) -> None:
    """
    Embed each chunk's ``text`` (via ``ai.get_embeddings``) and add to the
    index, tagging every resulting vector with *user_id* and *file_id* so
    ``search()`` can later restrict matches to their owner.

    Parameters
    ----------
    chunks:
        Output of ``app.chunking.chunk_entries`` — each dict has
        ``{"text": str, "entry_ids": list[int]}``.
    user_id:
        Owning user's id (``LogFile.uploaded_by``) — required so a caller
        can never retrieve another user's log lines via search().
    file_id:
        The source ``LogFile.id`` these chunks were parsed from.
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
        })

    if not valid_vecs:
        return

    matrix = np.array(valid_vecs, dtype=np.float32)

    with _LOCK:
        idx = _ensure_index()
        idx.add(matrix)
        _METADATA.extend(valid_meta)

    print(f"[vector_store] Added {len(valid_vecs)} chunk vectors for user={user_id} file={file_id} (total: {_ensure_index().ntotal})")


def add_entries(entries: list, user_id: str, file_id: int) -> None:
    """
    Convenience wrapper: chunk *entries* then call add_chunks(), tagging the
    resulting vectors with *user_id* and *file_id*.
    Uses app.chunking defaults (CHUNK_SIZE=10, CHUNK_OVERLAP=2).
    """
    from .chunking import chunk_entries
    add_chunks(chunk_entries(entries), user_id=user_id, file_id=file_id)


def search(query: str, user_id: str, k: int = 5, file_id: int | None = None) -> list[int]:
    """
    Embed *query* and return the LogEntry IDs of the top-k matching chunks
    that belong to *user_id* (and, if given, *file_id*).

    IndexFlatIP has no native per-vector metadata filtering, so this
    searches the *entire* flat index (cheap — IndexFlatIP is already an
    exhaustive linear scan, so requesting all ntotal results costs the same
    as requesting a handful) and then filters by user_id/file_id in ranked
    order, stopping once k matching chunks have been collected. Returns []
    when the index is empty or the user has no matching vectors.
    """
    from .ai import get_embedding

    with _LOCK:
        idx = _ensure_index()
        if idx.ntotal == 0:
            return []

        vec = np.array([get_embedding(query)], dtype=np.float32)
        _scores, positions = idx.search(vec, idx.ntotal)
        metadata_snapshot = _METADATA

    seen: set[int] = set()
    result: list[int] = []
    matched_chunks = 0
    for pos in positions[0]:
        if matched_chunks >= k:
            break
        if pos < 0 or pos >= len(metadata_snapshot):
            continue

        meta = metadata_snapshot[pos]
        if meta["user_id"] != user_id:
            continue
        if file_id is not None and meta["file_id"] != file_id:
            continue

        matched_chunks += 1
        for entry_id in meta["entry_ids"]:
            if entry_id not in seen:
                seen.add(entry_id)
                result.append(entry_id)

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
