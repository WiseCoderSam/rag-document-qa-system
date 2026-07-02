"""
Phase 4 regression suite (Tasks 1-6): chunking, per-user FAISS isolation,
RAG investigation chat, AI incident summaries, and log search.

Style matches test_parser_rules.py / test_auth.py: plain pytest functions,
direct imports from app, no fixture framework beyond monkeypatch. DB state
lives in a private in-memory sqlite engine, reset every test via
setup_function/teardown_function (xunit-style hooks, not @pytest.fixture),
alongside app.vector_store._reset() (see vector_store.py:140).

Run with:
    .\\venv\\Scripts\\pytest -v test_rag.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime
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

from app import ai, chunking, models, summarizer, vector_store
from app.auth import SUPABASE_JWT_SECRET
from app.database import get_db
from app.main import app
from app.processor import process_log_file_task

# ---------------------------------------------------------------------------
# Test database — private in-memory sqlite, shared across a test's Session()
# calls via StaticPool. main.py's own module-level create_all() still runs
# against the real engine at import time; this is separate and unaffected.
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
# real lifespan (folder watcher thread, FAISS index load from disk), which
# none of these tests need and which would leak a background thread.
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


def _make_entry(entry_id: int, message: str, **kwargs) -> models.LogEntry:
    """Construct a transient LogEntry without a DB session."""
    defaults = dict(
        file_id=1, severity="INFO", timestamp=None,
        ip_address=None, user_name=None, hostname=None, event_id=None, parsed_json=None,
    )
    defaults.update(kwargs)
    return models.LogEntry(id=entry_id, message=message, **defaults)


def _new_db():
    return _TestSessionLocal()


def _seed_log_file(db, uploaded_by: str, filename: str = "test.log", status: str = "completed") -> int:
    log_file = models.LogFile(filename=filename, file_url="local", status=status, uploaded_by=uploaded_by)
    db.add(log_file)
    db.commit()
    db.refresh(log_file)
    return log_file.id


def _seed_entry(db, file_id: int, message: str, **kwargs) -> int:
    defaults = dict(severity="INFO", timestamp=None, ip_address=None, user_name=None, hostname=None, event_id=None)
    defaults.update(kwargs)
    entry = models.LogEntry(file_id=file_id, message=message, **defaults)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry.id


def _write_temp_log(lines: list[str]) -> str:
    """Writes *lines* to a standalone temp .log file and returns its path."""
    tmp_dir = tempfile.mkdtemp()
    log_path = Path(tmp_dir) / "ingest_test.log"
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(log_path)


def _seed_incident(db, log_file_id: int | None, affected_ip: str | None = None, affected_user: str | None = None) -> models.Incident:
    incident = models.Incident(
        rule_name="Brute force login",
        severity="HIGH",
        mitre_technique="T1110",
        mitre_tactic="Credential Access",
        description="5+ failed logins from the same IP within 5 minutes.",
        affected_ip=affected_ip,
        affected_user=affected_user,
        log_file_id=log_file_id,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


# ---------------------------------------------------------------------------
# 1. Chunking (Task 1)
# ---------------------------------------------------------------------------

def test_chunk_entries_known_grouping():
    entries = [_make_entry(i, f"line {i}") for i in range(1, 26)]  # 25 entries

    chunks = chunking.chunk_entries(entries)
    step = chunking.CHUNK_SIZE - chunking.CHUNK_OVERLAP

    assert step == 8, "test assumes the current CHUNK_SIZE=10 / CHUNK_OVERLAP=2 defaults"
    assert [c["entry_ids"] for c in chunks] == [
        list(range(1, 11)),
        list(range(9, 19)),
        list(range(17, 26)),
    ]


def test_chunk_entries_single_chunk_when_fewer_than_chunk_size():
    entries = [_make_entry(i, f"line {i}") for i in range(1, 4)]

    chunks = chunking.chunk_entries(entries)

    assert len(chunks) == 1
    assert chunks[0]["entry_ids"] == [1, 2, 3]


def test_chunk_entries_empty_list():
    assert chunking.chunk_entries([]) == []


def test_chunk_entries_adjacent_chunks_share_overlap_ids():
    entries = [_make_entry(i, f"line {i}") for i in range(1, 26)]

    chunks = chunking.chunk_entries(entries)

    # Adjacent chunks share the overlapping ids so a match near a boundary
    # isn't lost to whichever side of the window it landed on.
    assert set(chunks[0]["entry_ids"]) & set(chunks[1]["entry_ids"]) == {9, 10}
    assert set(chunks[1]["entry_ids"]) & set(chunks[2]["entry_ids"]) == {17, 18}


def test_chunk_entries_line_format_includes_timestamp_severity_message():
    ts = datetime(2026, 7, 1, 12, 0, 0)
    entries = [_make_entry(1, "failed login", timestamp=ts, severity="WARNING")]

    chunks = chunking.chunk_entries(entries)

    assert chunks[0]["text"] == f"{ts.isoformat()} | WARNING | failed login"


def test_chunk_entries_missing_timestamp_falls_back_to_na():
    entries = [_make_entry(1, "no timestamp", timestamp=None)]

    chunks = chunking.chunk_entries(entries)

    assert chunks[0]["text"].startswith("N/A | INFO | no timestamp")


# ---------------------------------------------------------------------------
# 2. Per-user FAISS isolation (Task 2)
# ---------------------------------------------------------------------------

def test_vector_store_search_never_crosses_users(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    entries_a = [_make_entry(101, "Failed login for user alice from 1.1.1.1")]
    entries_b = [_make_entry(201, "Failed login for user bob from 2.2.2.2")]

    vector_store.add_entries(entries_a, user_id="user-a", file_id=1)
    vector_store.add_entries(entries_b, user_id="user-b", file_id=2)

    results_a = vector_store.search("failed login", "user-a", k=5)
    results_b = vector_store.search("failed login", "user-b", k=5)

    assert results_a == [101]
    assert results_b == [201]
    assert 201 not in results_a, "user-a's search leaked user-b's entry"
    assert 101 not in results_b, "user-b's search leaked user-a's entry"


def test_vector_store_search_empty_for_user_with_no_data(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    vector_store.add_entries([_make_entry(1, "some log line")], user_id="user-a", file_id=1)

    assert vector_store.search("anything", "user-c", k=5) == []


def test_vector_store_search_can_filter_by_file_id(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    vector_store.add_entries([_make_entry(301, "Failed login for user carol from 172.16.0.1")], user_id="user-a", file_id=1)
    vector_store.add_entries([_make_entry(302, "Failed login for user carol from 172.16.0.1")], user_id="user-a", file_id=2)

    results = vector_store.search("failed login", "user-a", k=5, file_id=1)
    assert results == [301], f"Expected only file_id=1's entry, got {results}"


def test_vector_store_save_and_load_round_trip(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)

    store_dir = Path(tempfile.mkdtemp())
    monkeypatch.setattr(vector_store, "_STORE_DIR", store_dir)
    monkeypatch.setattr(vector_store, "_INDEX_PATH", store_dir / "index.faiss")
    monkeypatch.setattr(vector_store, "_MAP_PATH", store_dir / "id_map.json")

    entries = [
        _make_entry(201, "User bob logged in successfully"),
        _make_entry(202, "Firewall rule denied traffic from 203.0.113.77"),
    ]
    # Both entries fit under CHUNK_SIZE, so they collapse into a single chunk/vector.
    vector_store.add_entries(entries, user_id="user-a", file_id=7)
    vector_store.save()

    assert (store_dir / "index.faiss").exists(), "index.faiss not written"
    assert (store_dir / "id_map.json").exists(), "id_map.json not written"

    saved_map = json.loads((store_dir / "id_map.json").read_text())
    assert saved_map == [{"entry_ids": [201, 202], "user_id": "user-a", "file_id": 7}], (
        f"Metadata mismatch: {saved_map}"
    )

    vector_store._reset()
    vector_store.load()

    assert vector_store._INDEX is not None, "_INDEX should be set after load()"
    assert vector_store._INDEX.ntotal == 1, f"Expected 1 chunk vector after reload, got {vector_store._INDEX.ntotal}"
    assert vector_store._METADATA == [{"entry_ids": [201, 202], "user_id": "user-a", "file_id": 7}], (
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


def test_answer_query_empty_context_returns_graceful_message():
    """ai.answer_query with no context entries must not call Gemini at all."""
    answer = ai.answer_query("any question", [])
    assert "no logs" in answer.lower() or "not been ingested" in answer.lower(), (
        f"Unexpected graceful message: {answer}"
    )


# ---------------------------------------------------------------------------
# 3/4. POST /api/v1/chat (Task 4)
# ---------------------------------------------------------------------------

def test_chat_requires_auth():
    resp = client.post("/api/v1/chat", json={"question": "anything"})
    assert resp.status_code == 401


def test_chat_returns_sources_for_seeded_entries(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)
    monkeypatch.setattr(ai, "generate_chat_response", lambda prompt, context="": "Mock chat answer.")

    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="chat-user")
    entry_id = _seed_entry(db, file_id, "Failed login for user hacker1 from 10.10.10.10", ip_address="10.10.10.10")
    db.close()

    vector_store.add_entries(
        [_make_entry(entry_id, "Failed login for user hacker1 from 10.10.10.10", ip_address="10.10.10.10")],
        user_id="chat-user",
        file_id=file_id,
    )

    resp = client.post(
        "/api/v1/chat",
        json={"question": "any failed logins?"},
        headers=_auth_headers("chat-user"),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Mock chat answer."
    assert body["sources"] == [entry_id]


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
    assert resp.json()["sources"] == []
    assert called["count"] == 0, "generate_chat_response must not be invoked with empty context"


def test_chat_with_incident_id_owned_by_another_user_returns_404(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    db = _new_db()
    other_file_id = _seed_log_file(db, uploaded_by="owner-user")
    incident = models.Incident(
        rule_name="Brute force login",
        severity="HIGH",
        description="test incident",
        log_file_id=other_file_id,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    incident_id = incident.id
    db.close()

    resp = client.post(
        "/api/v1/chat",
        json={"question": "summarize this", "incident_id": incident_id},
        headers=_auth_headers("intruder-user"),
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. AI incident summaries — context-building internals, auto
#    (processor.py), on-demand (/resummarize), and failure tolerance
# ---------------------------------------------------------------------------

def test_entries_for_incident_filters_by_affected_ip_or_user():
    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="user-a")
    matching_ip_id = _seed_entry(db, file_id, "Failed login from attacker IP", ip_address="9.9.9.9")
    matching_user_id = _seed_entry(db, file_id, "Failed login for targeted user", user_name="victim")
    unrelated_id = _seed_entry(db, file_id, "Unrelated GET /health 200 OK", ip_address="1.1.1.1", user_name="someone_else")

    incident = _seed_incident(db, file_id, affected_ip="9.9.9.9", affected_user="victim")
    entry_ids = {e.id for e in summarizer._entries_for_incident(db, incident)}
    db.close()

    assert matching_ip_id in entry_ids
    assert matching_user_id in entry_ids
    assert unrelated_id not in entry_ids


def test_entries_for_incident_falls_back_to_all_when_no_affected_fields():
    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="user-a")
    e1_id = _seed_entry(db, file_id, "line one")
    e2_id = _seed_entry(db, file_id, "line two")

    incident = _seed_incident(db, file_id, affected_ip=None, affected_user=None)
    entry_ids = {e.id for e in summarizer._entries_for_incident(db, incident)}
    db.close()

    assert entry_ids == {e1_id, e2_id}


def test_entries_for_incident_no_log_file_returns_empty():
    db = _new_db()
    incident = _seed_incident(db, log_file_id=None, affected_ip="9.9.9.9")
    result = summarizer._entries_for_incident(db, incident)
    db.close()

    assert result == []


def test_summarize_incident_prompt_includes_metadata_and_matching_entries_only(monkeypatch):
    captured = {}

    def fake_chat_response(prompt: str, context: str = "") -> str:
        captured["prompt"] = prompt
        return "Mock summary."

    monkeypatch.setattr(ai, "generate_chat_response", fake_chat_response)

    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="user-a")
    _seed_entry(db, file_id, "Failed login attempt from attacker", ip_address="9.9.9.9")
    _seed_entry(db, file_id, "Totally unrelated event", ip_address="1.1.1.1", user_name="bystander")
    incident = _seed_incident(db, file_id, affected_ip="9.9.9.9")

    result = summarizer.summarize_incident(db, incident)
    db.close()

    assert result == "Mock summary."
    assert "T1110" in captured["prompt"]
    assert "Credential Access" in captured["prompt"]
    assert "Brute force login" in captured["prompt"]
    assert "9.9.9.9" in captured["prompt"]
    assert "Failed login attempt from attacker" in captured["prompt"]
    assert "Totally unrelated event" not in captured["prompt"]


def test_summarize_incident_without_log_file_uses_fallback_context(monkeypatch):
    captured = {}

    def fake_chat_response(prompt: str, context: str = "") -> str:
        captured["prompt"] = prompt
        return "Mock summary."

    monkeypatch.setattr(ai, "generate_chat_response", fake_chat_response)

    db = _new_db()
    incident = _seed_incident(db, log_file_id=None, affected_ip="9.9.9.9")
    result = summarizer.summarize_incident(db, incident)
    db.close()

    assert result == "Mock summary."
    assert "no related log entries found" in captured["prompt"]


BRUTE_FORCE_LINES = [
    "2026-07-02 09:00:00 WARNING Failed login for user hacker1 from 10.10.10.10",
    "2026-07-02 09:00:10 WARNING Failed login for user hacker1 from 10.10.10.10",
    "2026-07-02 09:00:20 WARNING Failed login for user hacker1 from 10.10.10.10",
    "2026-07-02 09:00:30 WARNING Failed login for user hacker1 from 10.10.10.10",
    "2026-07-02 09:00:40 WARNING Failed login for user hacker1 from 10.10.10.10",
]


def _seed_processing_log_file(uploaded_by: str, lines: list[str]) -> int:
    db = _new_db()
    log_file = models.LogFile(
        filename="ingest.log", file_url=_write_temp_log(lines), status="processing", uploaded_by=uploaded_by,
    )
    db.add(log_file)
    db.commit()
    db.refresh(log_file)
    file_id = log_file.id
    db.close()
    return file_id


def test_process_log_file_task_populates_incident_summary(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "generate_chat_response", lambda prompt, context="": "Mock incident summary.")
    monkeypatch.setattr(vector_store, "save", lambda: None)  # avoid writing to backend/vector_store/ on disk

    file_id = _seed_processing_log_file("summary-user", BRUTE_FORCE_LINES)

    process_log_file_task(file_id, _new_db())

    db = _new_db()
    log_file = db.query(models.LogFile).filter(models.LogFile.id == file_id).first()
    incidents = db.query(models.Incident).filter(models.Incident.log_file_id == file_id).all()
    assert log_file.status == "completed"
    assert len(incidents) == 1
    assert incidents[0].summary == "Mock incident summary."
    db.close()


def test_resummarize_endpoint_updates_summary(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(ai, "generate_chat_response", lambda prompt, context="": "First summary.")
    monkeypatch.setattr(vector_store, "save", lambda: None)

    file_id = _seed_processing_log_file("resum-user", BRUTE_FORCE_LINES)
    process_log_file_task(file_id, _new_db())

    db = _new_db()
    incident = db.query(models.Incident).filter(models.Incident.log_file_id == file_id).first()
    incident_id = incident.id
    assert incident.summary == "First summary."
    db.close()

    monkeypatch.setattr(ai, "generate_chat_response", lambda prompt, context="": "Regenerated summary.")

    resp = client.post(f"/api/v1/incidents/{incident_id}/resummarize", headers=_auth_headers("resum-user"))

    assert resp.status_code == 200
    assert resp.json()["summary"] == "Regenerated summary."

    db = _new_db()
    reloaded = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    assert reloaded.summary == "Regenerated summary."
    db.close()


def test_process_log_file_task_survives_summarizer_failure(monkeypatch):
    monkeypatch.setattr(ai, "get_embeddings", _stub_embeddings)
    monkeypatch.setattr(vector_store, "save", lambda: None)

    def boom(db, incident):
        raise RuntimeError("simulated Gemini outage")

    monkeypatch.setattr(summarizer, "summarize_incident", boom)

    file_id = _seed_processing_log_file("fail-user", BRUTE_FORCE_LINES)

    process_log_file_task(file_id, _new_db())

    db = _new_db()
    log_file = db.query(models.LogFile).filter(models.LogFile.id == file_id).first()
    incidents = db.query(models.Incident).filter(models.Incident.log_file_id == file_id).all()
    assert log_file.status == "completed", "a summarizer failure must not abort the whole ingestion"
    assert len(incidents) == 1
    assert incidents[0].summary is None
    db.close()


# ---------------------------------------------------------------------------
# 6. GET /api/v1/logs/search
# ---------------------------------------------------------------------------

def test_log_search_requires_at_least_one_filter():
    resp = client.get("/api/v1/logs/search", headers=_auth_headers("search-user-a"))
    assert resp.status_code == 400


def test_log_search_filters_and_scopes_to_current_user():
    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="search-user-a")
    entry_a_id = _seed_entry(
        db, file_id, "Failed login",
        ip_address="9.9.9.9", user_name="alice", hostname="host1", event_id="4625", severity="WARNING",
    )
    entry_b_id = _seed_entry(
        db, file_id, "Accepted login",
        ip_address="8.8.8.8", user_name="bob", hostname="host2", event_id="4624", severity="INFO",
    )

    other_file_id = _seed_log_file(db, uploaded_by="search-user-b")
    _seed_entry(db, other_file_id, "Failed login elsewhere", ip_address="9.9.9.9", user_name="alice", severity="WARNING")
    db.close()

    # Single filter narrows to the matching entry.
    resp = client.get("/api/v1/logs/search", params={"ip": "9.9.9.9"}, headers=_auth_headers("search-user-a"))
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [entry_a_id]

    resp = client.get("/api/v1/logs/search", params={"hostname": "host2"}, headers=_auth_headers("search-user-a"))
    assert [row["id"] for row in resp.json()] == [entry_b_id]

    resp = client.get("/api/v1/logs/search", params={"event_id": "4624"}, headers=_auth_headers("search-user-a"))
    assert [row["id"] for row in resp.json()] == [entry_b_id]

    # Filters are ANDed: alice's entry is WARNING, not INFO, so this excludes it.
    resp = client.get(
        "/api/v1/logs/search",
        params={"user": "alice", "severity": "INFO"},
        headers=_auth_headers("search-user-a"),
    )
    assert resp.json() == []

    # search-user-b also has a matching ip=9.9.9.9 entry of their own, but it
    # must never appear in search-user-a's results, and vice versa.
    resp_a = client.get("/api/v1/logs/search", params={"ip": "9.9.9.9"}, headers=_auth_headers("search-user-a"))
    ids_a = [row["id"] for row in resp_a.json()]
    resp_b = client.get("/api/v1/logs/search", params={"ip": "9.9.9.9"}, headers=_auth_headers("search-user-b"))
    ids_b = [row["id"] for row in resp_b.json()]

    assert ids_a == [entry_a_id]
    assert entry_a_id not in ids_b


def test_log_search_pagination_orders_by_timestamp_desc():
    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="search-user-a")
    made_ids = [
        _seed_entry(db, file_id, f"m{i}", hostname="bulk-host", severity="INFO", timestamp=datetime(2026, 7, 2, 9, i, 0))
        for i in range(5)
    ]
    db.close()

    expected_order = list(reversed(made_ids))  # later timestamp (higher i) first

    resp1 = client.get(
        "/api/v1/logs/search", params={"hostname": "bulk-host", "limit": 2, "offset": 0}, headers=_auth_headers("search-user-a")
    )
    resp2 = client.get(
        "/api/v1/logs/search", params={"hostname": "bulk-host", "limit": 2, "offset": 2}, headers=_auth_headers("search-user-a")
    )

    assert [row["id"] for row in resp1.json()] == expected_order[:2]
    assert [row["id"] for row in resp2.json()] == expected_order[2:4]


def test_log_search_limit_is_capped(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "SEARCH_MAX_LIMIT", 3)

    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="search-user-a")
    for i in range(5):
        _seed_entry(db, file_id, f"m{i}", hostname="cap-host", severity="INFO", timestamp=datetime(2026, 7, 2, 9, i, 0))
    db.close()

    resp = client.get(
        "/api/v1/logs/search", params={"hostname": "cap-host", "limit": 1000}, headers=_auth_headers("search-user-a")
    )
    assert len(resp.json()) == 3


# ---------------------------------------------------------------------------
# 7. GET /api/v1/logs/entries — resolves chat/query citation ids to content
# ---------------------------------------------------------------------------

def test_log_entries_resolves_ids_to_full_content():
    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="entries-user")
    entry_id = _seed_entry(db, file_id, "Failed login for user alice from 1.2.3.4", ip_address="1.2.3.4")
    db.close()

    resp = client.get("/api/v1/logs/entries", params={"ids": str(entry_id)}, headers=_auth_headers("entries-user"))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == entry_id
    assert body[0]["message"] == "Failed login for user alice from 1.2.3.4"
    assert body[0]["ip_address"] == "1.2.3.4"


def test_log_entries_accepts_comma_separated_ids():
    db = _new_db()
    file_id = _seed_log_file(db, uploaded_by="entries-user")
    id_a = _seed_entry(db, file_id, "line a")
    id_b = _seed_entry(db, file_id, "line b")
    id_c = _seed_entry(db, file_id, "line c")
    db.close()

    resp = client.get(
        "/api/v1/logs/entries", params={"ids": f"{id_a},{id_b}"}, headers=_auth_headers("entries-user")
    )

    assert resp.status_code == 200
    returned_ids = {row["id"] for row in resp.json()}
    assert returned_ids == {id_a, id_b}
    assert id_c not in returned_ids


def test_log_entries_never_returns_another_users_entries():
    db = _new_db()
    file_id_a = _seed_log_file(db, uploaded_by="entries-user-a")
    file_id_b = _seed_log_file(db, uploaded_by="entries-user-b", filename="other.log")
    id_a = _seed_entry(db, file_id_a, "user a's line")
    id_b = _seed_entry(db, file_id_b, "user b's line")
    db.close()

    resp = client.get(
        "/api/v1/logs/entries", params={"ids": f"{id_a},{id_b}"}, headers=_auth_headers("entries-user-a")
    )

    assert resp.status_code == 200
    returned_ids = {row["id"] for row in resp.json()}
    assert returned_ids == {id_a}, f"user-a's request leaked user-b's entry: {returned_ids}"


def test_log_entries_unknown_or_missing_ids_are_silently_omitted():
    resp = client.get("/api/v1/logs/entries", params={"ids": "99999"}, headers=_auth_headers("entries-user"))

    assert resp.status_code == 200
    assert resp.json() == []


def test_log_entries_rejects_non_integer_ids():
    resp = client.get("/api/v1/logs/entries", params={"ids": "abc"}, headers=_auth_headers("entries-user"))

    assert resp.status_code == 400
