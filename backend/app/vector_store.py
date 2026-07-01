"""
Singleton FAISS vector store for log entry chunk embeddings.

Each FAISS vector corresponds to a *chunk* (a window of log lines) produced
by app.chunking.  The ID map stores lists of LogEntry.id values so that
a similarity hit can be traced back to its source entries.

Public API
----------
add_chunks(chunks)  — embed a list of chunk dicts and insert into the index
add_entries(entries) — convenience: chunk then embed raw LogEntry objects
search(query, k)    — embed query and return flat list of matching LogEntry IDs
save() / load()     — persist index and ID map to disk
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
_INDEX = None           # faiss.IndexFlatIP — lazily imported
_ID_MAP: list[list[int]] = []  # position i → list of LogEntry.id in that chunk

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

def add_chunks(chunks: list[dict]) -> None:
    """
    Embed each chunk's ``text`` (via ``ai.get_embeddings``) and add to the index.

    Parameters
    ----------
    chunks:
        Output of ``app.chunking.chunk_entries`` — each dict has
        ``{"text": str, "entry_ids": list[int]}``.
    """
    if not chunks:
        return

    from .ai import get_embeddings  # local import avoids circular deps

    texts = [c["text"] for c in chunks]
    vecs  = get_embeddings(texts)

    valid_vecs  = []
    valid_ids   = []
    for vec, chunk in zip(vecs, chunks):
        if not chunk["entry_ids"]:
            continue
        valid_vecs.append(vec)
        valid_ids.append(chunk["entry_ids"])

    if not valid_vecs:
        return

    matrix = np.array(valid_vecs, dtype=np.float32)

    with _LOCK:
        idx = _ensure_index()
        idx.add(matrix)
        _ID_MAP.extend(valid_ids)

    print(f"[vector_store] Added {len(valid_vecs)} chunk vectors (total: {_ensure_index().ntotal})")


def add_entries(entries: list) -> None:
    """
    Convenience wrapper: chunk *entries* then call add_chunks().
    Uses app.chunking defaults (CHUNK_SIZE=10, CHUNK_OVERLAP=2).
    """
    from .chunking import chunk_entries
    add_chunks(chunk_entries(entries))


def search(query: str, k: int = 5) -> list[int]:
    """
    Embed *query* and return the LogEntry IDs of the top-k matching chunks.

    IDs from all matching chunks are merged and deduplicated while preserving
    relevance order.  Returns [] when the index is empty.
    """
    from .ai import get_embedding

    with _LOCK:
        idx = _ensure_index()
        if idx.ntotal == 0:
            return []

        actual_k = min(k, idx.ntotal)
        vec = np.array([get_embedding(query)], dtype=np.float32)
        _scores, positions = idx.search(vec, actual_k)

    seen: set[int] = set()
    result: list[int] = []
    for pos in positions[0]:
        if pos < 0 or pos >= len(_ID_MAP):
            continue
        for entry_id in _ID_MAP[pos]:
            if entry_id not in seen:
                seen.add(entry_id)
                result.append(entry_id)

    return result


def save() -> None:
    """Persist the index and ID map to disk."""
    faiss = _get_faiss()
    _STORE_DIR.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        idx = _ensure_index()
        faiss.write_index(idx, str(_INDEX_PATH))
        _MAP_PATH.write_text(json.dumps(_ID_MAP), encoding="utf-8")

    print(f"[vector_store] Saved {idx.ntotal} chunk vectors to {_STORE_DIR}")


def load() -> None:
    """Load a previously persisted index and ID map from disk."""
    global _INDEX, _ID_MAP

    if not _INDEX_PATH.exists() or not _MAP_PATH.exists():
        print("[vector_store] No persisted index found — starting fresh.")
        return

    faiss = _get_faiss()
    with _LOCK:
        _INDEX  = faiss.read_index(str(_INDEX_PATH))
        _ID_MAP = json.loads(_MAP_PATH.read_text(encoding="utf-8"))

    print(f"[vector_store] Loaded {_INDEX.ntotal} chunk vectors from {_STORE_DIR}")


# ---------------------------------------------------------------------------
# Test helper — NOT for production use
# ---------------------------------------------------------------------------

def _reset() -> None:
    """Reset singleton state. Used only by the pytest test suite."""
    global _INDEX, _ID_MAP
    with _LOCK:
        _INDEX  = None
        _ID_MAP = []
