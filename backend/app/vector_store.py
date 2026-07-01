"""
Singleton FAISS vector store for log entry embeddings.

The index is a flat inner-product index over 768-dimensional vectors
produced by Google text-embedding-004.  All public functions are
thread-safe for the typical single-writer / multiple-reader pattern of
a FastAPI + BackgroundTasks setup.
"""

import json
import threading
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_DIM = 768
_INDEX = None          # faiss.IndexFlatIP — lazily imported
_ID_MAP: list[int] = []  # position i in the FAISS index → LogEntry.id

_STORE_DIR = Path(__file__).resolve().parent.parent / "vector_store"
_INDEX_PATH = _STORE_DIR / "index.faiss"
_MAP_PATH   = _STORE_DIR / "id_map.json"


def _get_faiss():
    """Import faiss lazily so the module can be imported without it installed."""
    import faiss  # noqa: F401  (optional dep — faiss-cpu)
    return faiss


def _ensure_index():
    """Return the singleton index, creating it if necessary."""
    global _INDEX
    if _INDEX is None:
        faiss = _get_faiss()
        _INDEX = faiss.IndexFlatIP(_DIM)
    return _INDEX


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_entries(entries: list) -> None:
    """
    Embed each LogEntry's ``message`` and add it to the FAISS index.

    Parameters
    ----------
    entries:
        Iterable of objects that have an ``id: int`` and a ``message: str``
        attribute (i.e. ``app.models.LogEntry`` instances).
    """
    if not entries:
        return

    from .ai import get_embedding  # local import avoids circular deps

    vectors = []
    ids     = []
    for entry in entries:
        text = (entry.message or "").strip()
        if not text:
            continue
        vec = get_embedding(text)
        vectors.append(vec)
        ids.append(entry.id)

    if not vectors:
        return

    matrix = np.array(vectors, dtype=np.float32)

    with _LOCK:
        idx = _ensure_index()
        idx.add(matrix)
        _ID_MAP.extend(ids)

    print(f"[vector_store] Added {len(vectors)} vectors (total: {_ensure_index().ntotal})")


def search(query: str, k: int = 5) -> list[int]:
    """
    Embed *query* and return the IDs of the top-k most similar LogEntries.

    Returns an empty list when the index is empty.
    """
    from .ai import get_embedding

    with _LOCK:
        idx = _ensure_index()
        if idx.ntotal == 0:
            return []

        actual_k = min(k, idx.ntotal)
        vec = np.array([get_embedding(query)], dtype=np.float32)
        _scores, positions = idx.search(vec, actual_k)

    return [_ID_MAP[pos] for pos in positions[0] if pos >= 0]


def save() -> None:
    """Persist the index and the ID map to disk."""
    faiss = _get_faiss()
    _STORE_DIR.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        idx = _ensure_index()
        faiss.write_index(idx, str(_INDEX_PATH))
        _MAP_PATH.write_text(json.dumps(_ID_MAP), encoding="utf-8")

    print(f"[vector_store] Saved {idx.ntotal} vectors to {_STORE_DIR}")


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

    print(f"[vector_store] Loaded {_INDEX.ntotal} vectors from {_STORE_DIR}")


# ---------------------------------------------------------------------------
# Test helper — NOT for production use
# ---------------------------------------------------------------------------

def _reset() -> None:
    """Reset the singleton state.  Used only by the pytest test suite."""
    global _INDEX, _ID_MAP
    with _LOCK:
        _INDEX  = None
        _ID_MAP = []
