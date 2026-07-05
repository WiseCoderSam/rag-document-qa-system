"""
Regression suite for the Document Q&A backend: text chunking, per-user
FAISS isolation, the RAG chat endpoint, and document-chunk citation
resolution.

Style matches test_auth.py: plain pytest functions, direct imports from
app, no fixture framework beyond monkeypatch. DB state lives in a private
in-memory sqlite engine, reset every test via setup_function/
teardown_function (xunit-style hooks, not @pytest.fixture), alongside
app.vector_store._reset().

Run with:
    .\\venv\\Scripts\\pytest -v test_rag.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Unset key so ai.py doesn't try to call Gemini during import.
os.environ.pop("GEMINI_API_KEY", None)

import jwt
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import ai, models, vector_store
from app.auth import SUPABASE_JWT_SECRET
from app.database import get_db
from app.doc_processor import _chunk_text
from app.main import NO_MATCH_ANSWER, app

# ---------------------------------------------------------------------------
# Test database — private in-memory sqlite, shared across a test's Session()
# calls via StaticPool. Schema is created directly against this engine below
# (see Base.metadata.create_all(bind=_engine)) rather than relying on
# app.main, which no longer creates tables itself (schema is Alembic-managed
# — see app/main.py).
# ---------------------------------------------------------------------------

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine)


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Not using `with TestClient(app) as ...` on purpose: that would trigger the
# real lifespan (FAISS index load from disk), which none of these tests need.
client = TestClient(app)


def setup_function(_function):
    models.Base.metadata.drop_all(bind=_engine)
    models.Base.metadata.create_all(bind=_engine)
    vector_store._reset()
    # Re-set every test (rather than once at import time) since another test
    # module running earlier in the same pytest session may have called
    # app.dependency_overrides.clear() in its own teardown.
    app.dependency_overrides[get_db] = _override_get_db


def teardown_function(_function):
    vector_store._reset()
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _stub_embedding(text: str) -> list[float]:
    """Deterministic non-zero embedding stub (uses hash for variety)."""
    seed = sum(ord(c) for c in text) % 256
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(768).astype(np.float32)
    norm = np.linalg.norm(vec)
    return (vec / norm).tolist()


def _stub_embeddings(texts: list[str]) -> list[list[float]]:
    return [_stub_embedding(t) for t in texts]


def _auth_headers(user_id: str, email: str = "test@example.com") -> dict:
    token = jwt.encode({"sub": user_id, "email": email, "aud": "authenticated"}, SUPABASE_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _new_db():
    return _TestSessionLocal()


def _seed_document(db, uploaded_by: str, filename: str = "test.pdf", status: str = "completed") -> int:
    document = models.Document(filename=filename, file_url="local", status=status, uploaded_by=uploaded_by)
    db.add(document)
    db.commit()
    db.refresh(document)
    return document.id


def _seed_document_chunk(db, document_id: int, text: str, chunk_index: int = 0) -> int:
    chunk = models.DocumentChunk(document_id=document_id, chunk_index=chunk_index, text=text)
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return chunk.id


def _index_chunk(chunk_id: int, text: str, user_id: str, document_id: int) -> None:
    """Add one already-persisted DocumentChunk to the FAISS index."""
    vector_store.add_chunks(
        [{"text": text, "entry_ids": [chunk_id]}],
        user_id=user_id,
        file_id=document_id,
        kind="document",
    )


# ---------------------------------------------------------------------------
# 1. Text chunking (doc_processor._chunk_text)
# ---------------------------------------------------------------------------

def test_chunk_text_short_input_single_chunk():
    chunks = _chunk_text("short document text")
    assert len(chunks) == 1
    assert chunks[0] == {"text": "short document text", "chunk_index": 0}


def test_chunk_text_windows_overlap():
    from app.doc_processor import CHUNK_OVERLAP, CHUNK_SIZE

    text = "a" * (CHUNK_SIZE + 100)
    chunks = _chunk_text(text)
    assert len(chunks) == 2
    assert chunks[0]["text"] == "a" * CHUNK_SIZE
    # Second window starts CHUNK_SIZE - CHUNK_OVERLAP in, so the two chunks
    # share CHUNK_OVERLAP characters.
    assert len(chunks[1]["text"]) == 100 + CHUNK_OVERLAP
    assert [c["chunk_index"] for c in chunks] == [0, 1]


def test_chunk_text_empty_input():
    assert _chunk_text("") == []
    assert _chunk_text("   \n  ") == []


# ---------------------------------------------------------------------------
# 2. Vector store — per-user isolation and kind filtering
# ---------------------------------------------------------------------------

def test_vector_store_search_never_crosses_users(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    _index_chunk(101, "The quarterly revenue grew by 12 percent", user_id="user-a", document_id=1)
    _index_chunk(201, "The quarterly revenue grew by 12 percent", user_id="user-b", document_id=2)

    results_a = [r["id"] for r in vector_store.search("revenue growth", "user-a", k=5)]
    results_b = [r["id"] for r in vector_store.search("revenue growth", "user-b", k=5)]

    assert results_a == [101]
    assert results_b == [201]
    assert 201 not in results_a, "user-a's search leaked user-b's chunk"
    assert 101 not in results_b, "user-b's search leaked user-a's chunk"


def test_vector_store_search_empty_for_user_with_no_data(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    _index_chunk(1, "some document text", user_id="user-a", document_id=1)

    assert vector_store.search("anything", "user-c", k=5) == []


def test_vector_store_search_can_filter_by_file_id(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    _index_chunk(301, "Contract renewal terms for 2026", user_id="user-a", document_id=1)
    _index_chunk(302, "Contract renewal terms for 2026", user_id="user-a", document_id=2)

    results = vector_store.search("contract renewal", "user-a", k=5, file_id=1, kind="document")
    assert results == [{"id": 301, "kind": "document"}], f"Expected only document 1's chunk, got {results}"


def test_vector_store_search_kind_filter_excludes_legacy_log_vectors(monkeypatch):
    """
    A persisted index from an install that predates the log-feature removal
    can still hold kind="log" vectors — a kind="document" search must never
    surface them, even when user_id/file_id match.
    """
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    vector_store.add_chunks(
        [{"text": "Failed login for user carol", "entry_ids": [401]}],
        user_id="user-a", file_id=1, kind="log",
    )
    _index_chunk(9001, "Failed login for user carol", user_id="user-a", document_id=1)

    doc_results = vector_store.search("failed login", "user-a", k=5, file_id=1, kind="document")
    assert doc_results == [{"id": 9001, "kind": "document"}]


def test_vector_store_search_legacy_metadata_without_kind_defaults_to_log(monkeypatch):
    """Vectors persisted before the kind field existed resolve as kind="log"
    — which means a kind="document" search correctly skips them."""
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    _index_chunk(501, "legacy vector", user_id="user-a", document_id=1)
    # Simulate metadata persisted by a version of the code with no "kind" key.
    del vector_store._METADATA[0]["kind"]

    assert vector_store.search("legacy vector", "user-a", k=5) == [{"id": 501, "kind": "log"}]
    assert vector_store.search("legacy vector", "user-a", k=5, kind="document") == []


def test_vector_store_save_and_load_round_trip(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)

    store_dir = Path(tempfile.mkdtemp())
    monkeypatch.setattr(vector_store, "_STORE_DIR", store_dir)
    monkeypatch.setattr(vector_store, "_INDEX_PATH", store_dir / "index.faiss")
    monkeypatch.setattr(vector_store, "_MAP_PATH", store_dir / "id_map.json")

    _index_chunk(201, "Employee handbook section on remote work", user_id="user-a", document_id=7)
    vector_store.save()

    assert (store_dir / "index.faiss").exists(), "index.faiss not written"
    assert (store_dir / "id_map.json").exists(), "id_map.json not written"

    saved_map = json.loads((store_dir / "id_map.json").read_text())
    assert saved_map == [{"entry_ids": [201], "user_id": "user-a", "file_id": 7, "kind": "document"}], (
        f"Metadata mismatch: {saved_map}"
    )

    vector_store._reset()
    vector_store.load()

    assert vector_store._INDEX is not None, "_INDEX should be set after load()"
    assert vector_store._INDEX.ntotal == 1, f"Expected 1 chunk vector after reload, got {vector_store._INDEX.ntotal}"
    assert vector_store._METADATA == [{"entry_ids": [201], "user_id": "user-a", "file_id": 7, "kind": "document"}], (
        f"Metadata after reload: {vector_store._METADATA}"
    )


def test_get_embeddings_no_key():
    """With GEMINI_API_KEY unset, get_embeddings must return 768-zero vectors."""
    original = ai.GEMINI_API_KEY
    ai.GEMINI_API_KEY = ""
    try:
        results = ai.get_embeddings(["any text", "another text"])
        assert len(results) == 2, f"Expected one vector per input text, got {len(results)}"
        for result in results:
            assert len(result) == 768, f"Expected 768 dimensions, got {len(result)}"
            assert all(v == 0.0 for v in result), "Expected all-zero fallback vector"
    finally:
        ai.GEMINI_API_KEY = original


# ---------------------------------------------------------------------------
# 3. POST /api/v1/chat
# ---------------------------------------------------------------------------

def test_chat_requires_auth():
    resp = client.post("/api/v1/chat", json={"question": "anything"})
    assert resp.status_code == 401


def test_chat_returns_sources_for_seeded_chunks(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)
    monkeypatch.setattr(ai, "generate_chat_response", lambda prompt, context="": "Mock chat answer.")

    db = _new_db()
    document_id = _seed_document(db, uploaded_by="chat-user")
    chunk_id = _seed_document_chunk(db, document_id, "The warranty period is 24 months.")
    db.close()

    _index_chunk(chunk_id, "The warranty period is 24 months.", user_id="chat-user", document_id=document_id)

    resp = client.post(
        "/api/v1/chat",
        json={"question": "how long is the warranty?"},
        headers=_auth_headers("chat-user"),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Mock chat answer."
    assert body["sources"] == [chunk_id]


def test_chat_returns_fixed_message_without_calling_llm_when_no_match(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    called = {"count": 0}

    def fail_if_called(prompt, context=""):
        called["count"] += 1
        return "should not be called"

    monkeypatch.setattr(ai, "generate_chat_response", fail_if_called)

    resp = client.post(
        "/api/v1/chat",
        json={"question": "anything"},
        headers=_auth_headers("empty-user"),
    )

    assert resp.status_code == 200
    assert resp.json()["answer"] == NO_MATCH_ANSWER
    assert resp.json()["sources"] == []
    assert called["count"] == 0, "LLM must not be called when retrieval finds nothing"


def test_chat_scoped_to_document_excludes_other_documents(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)
    monkeypatch.setattr(ai, "generate_chat_response", lambda prompt, context="": "Scoped answer.")

    db = _new_db()
    doc_1 = _seed_document(db, uploaded_by="scope-user", filename="a.pdf")
    doc_2 = _seed_document(db, uploaded_by="scope-user", filename="b.pdf")
    chunk_1 = _seed_document_chunk(db, doc_1, "Refund policy: 30 days, no questions asked.")
    chunk_2 = _seed_document_chunk(db, doc_2, "Refund policy: store credit only.")
    db.close()

    _index_chunk(chunk_1, "Refund policy: 30 days, no questions asked.", user_id="scope-user", document_id=doc_1)
    _index_chunk(chunk_2, "Refund policy: store credit only.", user_id="scope-user", document_id=doc_2)

    resp = client.post(
        "/api/v1/chat",
        json={"question": "what is the refund policy?", "document_id": doc_1},
        headers=_auth_headers("scope-user"),
    )

    assert resp.status_code == 200
    assert resp.json()["sources"] == [chunk_1]


def test_chat_scoped_to_another_users_document_returns_404(monkeypatch):
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)

    db = _new_db()
    other_doc = _seed_document(db, uploaded_by="owner-user")
    db.close()

    resp = client.post(
        "/api/v1/chat",
        json={"question": "anything", "document_id": other_doc},
        headers=_auth_headers("intruder-user"),
    )
    assert resp.status_code == 404


def test_chat_never_surfaces_legacy_log_vectors(monkeypatch):
    """
    Unscoped chat must filter to kind="document": a persisted index from
    before the log-feature removal can still contain log vectors whose ids
    resolve to nothing (or worse, to an unrelated DocumentChunk id).
    """
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)
    monkeypatch.setattr(ai, "generate_chat_response", lambda prompt, context="": "Answer.")

    vector_store.add_chunks(
        [{"text": "Failed login burst from 10.0.0.5", "entry_ids": [777]}],
        user_id="legacy-user", file_id=3, kind="log",
    )

    resp = client.post(
        "/api/v1/chat",
        json={"question": "failed login burst"},
        headers=_auth_headers("legacy-user"),
    )

    assert resp.status_code == 200
    assert resp.json()["answer"] == NO_MATCH_ANSWER
    assert resp.json()["sources"] == []


# ---------------------------------------------------------------------------
# 4. Document chunk citation resolution
# ---------------------------------------------------------------------------

def test_document_chunks_resolves_ids_to_full_content():
    db = _new_db()
    document_id = _seed_document(db, uploaded_by="res-user")
    chunk_a = _seed_document_chunk(db, document_id, "First chunk text.", chunk_index=0)
    chunk_b = _seed_document_chunk(db, document_id, "Second chunk text.", chunk_index=1)
    db.close()

    resp = client.get(
        f"/api/v1/documents/chunks?ids={chunk_a},{chunk_b}",
        headers=_auth_headers("res-user"),
    )

    assert resp.status_code == 200
    by_id = {c["id"]: c for c in resp.json()}
    assert by_id[chunk_a]["text"] == "First chunk text."
    assert by_id[chunk_b]["text"] == "Second chunk text."


def test_document_chunks_never_returns_another_users_chunks():
    db = _new_db()
    document_id = _seed_document(db, uploaded_by="owner-user")
    chunk_id = _seed_document_chunk(db, document_id, "Private text.")
    db.close()

    resp = client.get(
        f"/api/v1/documents/chunks?ids={chunk_id}",
        headers=_auth_headers("someone-else"),
    )

    assert resp.status_code == 200
    assert resp.json() == []


def test_document_chunks_rejects_non_integer_ids():
    resp = client.get(
        "/api/v1/documents/chunks?ids=1,abc",
        headers=_auth_headers("res-user"),
    )
    assert resp.status_code == 400


def test_document_chunks_listing_is_ordered_and_owner_scoped():
    db = _new_db()
    document_id = _seed_document(db, uploaded_by="list-user")
    _seed_document_chunk(db, document_id, "chunk one", chunk_index=1)
    _seed_document_chunk(db, document_id, "chunk zero", chunk_index=0)
    db.close()

    resp = client.get(f"/api/v1/documents/{document_id}/chunks", headers=_auth_headers("list-user"))
    assert resp.status_code == 200
    assert [c["chunk_index"] for c in resp.json()] == [0, 1]

    resp = client.get(f"/api/v1/documents/{document_id}/chunks", headers=_auth_headers("someone-else"))
    assert resp.status_code == 404
