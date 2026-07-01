"""
Phase 4 — AI & RAG Pipeline Unit Tests
======================================
All tests run fully offline:
  - No live Gemini API calls (get_embedding / generate_chat_response are monkeypatched)
  - No database session (LogEntry / Incident constructed directly)
  - No network I/O

Run with:
    .\\venv\\Scripts\\pytest -v test_ai_rag.py
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

# Make sure the backend package is importable when running from the backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Unset key so ai.py doesn't try to call Gemini during import
os.environ.pop("GEMINI_API_KEY", None)

from app import ai, vector_store
from app import models


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_vector_store():
    """Reset the singleton index before and after every test."""
    vector_store._reset()
    yield
    vector_store._reset()


def _stub_embedding(text: str) -> list[float]:
    """Deterministic non-zero embedding stub (uses hash for variety)."""
    seed = sum(ord(c) for c in text) % 256
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(768).astype(np.float32)
    # Normalize so inner-product behaves like cosine similarity
    norm = np.linalg.norm(vec)
    return (vec / norm).tolist()


def _make_entry(entry_id: int, message: str, severity: str = "INFO") -> models.LogEntry:
    """Construct a transient LogEntry without a DB session."""
    return models.LogEntry(
        id=entry_id,
        file_id=1,
        message=message,
        severity=severity,
        timestamp=None,
        ip_address=None,
        user_name=None,
        hostname=None,
        event_id=None,
        parsed_json=None,
    )


def _make_incident(**kwargs) -> models.Incident:
    """Construct a transient Incident without a DB session."""
    defaults = dict(
        id=1,
        rule_name="Brute force login",
        severity="HIGH",
        mitre_technique="T1110",
        mitre_tactic="Credential Access",
        affected_ip="10.0.0.5",
        affected_user="admin",
        description="5+ failed logins from the same IP within 5 minutes.",
        summary=None,
        log_file_id=1,
    )
    defaults.update(kwargs)
    return models.Incident(**defaults)


# ---------------------------------------------------------------------------
# Test 1 — get_embedding falls back to zero-vector without an API key
# ---------------------------------------------------------------------------

def test_get_embedding_no_key():
    """With GEMINI_API_KEY unset, get_embedding must return 768 zeros."""
    # Force the module-level key to empty (it was already unset above, but be explicit)
    original = ai.GEMINI_API_KEY
    ai.GEMINI_API_KEY = ""
    try:
        result = ai.get_embedding("any text")
        assert isinstance(result, list), "Expected a list"
        assert len(result) == 768, f"Expected 768 dimensions, got {len(result)}"
        assert all(v == 0.0 for v in result), "Expected all-zero fallback vector"
    finally:
        ai.GEMINI_API_KEY = original


# ---------------------------------------------------------------------------
# Test 2 — add_entries + search returns ranked IDs
# ---------------------------------------------------------------------------

def test_vector_store_add_and_search(monkeypatch):
    """Adding 3 entries then searching should return a non-empty ranked list of IDs."""
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    entries = [
        _make_entry(101, "Failed login for user alice from 192.168.1.5", "WARNING"),
        _make_entry(102, "GET /index.html 200 OK", "INFO"),
        _make_entry(103, "SQL injection attempt: UNION SELECT password FROM users", "CRITICAL"),
    ]

    vector_store.add_entries(entries)

    results = vector_store.search("failed login brute force", k=3)
    assert isinstance(results, list), "search() must return a list"
    assert len(results) > 0, "Expected at least one result"
    assert all(r in [101, 102, 103] for r in results), f"Unexpected IDs returned: {results}"


# ---------------------------------------------------------------------------
# Test 3 — save() + load() round-trip without data loss
# ---------------------------------------------------------------------------

def test_vector_store_save_and_load(monkeypatch, tmp_path):
    """Index persisted to a temp dir and reloaded must have the same ntotal."""
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    # Redirect store paths to tmp_path
    monkeypatch.setattr(vector_store, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(vector_store, "_INDEX_PATH", tmp_path / "index.faiss")
    monkeypatch.setattr(vector_store, "_MAP_PATH", tmp_path / "id_map.json")

    entries = [
        _make_entry(201, "User bob logged in successfully"),
        _make_entry(202, "Firewall rule denied traffic from 203.0.113.77"),
    ]
    vector_store.add_entries(entries)
    vector_store.save()

    # Verify files exist
    assert (tmp_path / "index.faiss").exists(), "index.faiss not written"
    assert (tmp_path / "id_map.json").exists(), "id_map.json not written"

    # Verify ID map content
    saved_map = json.loads((tmp_path / "id_map.json").read_text())
    assert saved_map == [201, 202], f"ID map mismatch: {saved_map}"

    # Reset and reload
    vector_store._reset()
    vector_store.load()

    import faiss
    # The internal index should have 2 vectors after reload
    assert vector_store._INDEX is not None, "_INDEX should be set after load()"
    assert vector_store._INDEX.ntotal == 2, f"Expected 2 vectors after reload, got {vector_store._INDEX.ntotal}"
    assert vector_store._ID_MAP == [201, 202], f"ID map after reload: {vector_store._ID_MAP}"


# ---------------------------------------------------------------------------
# Test 4 — search on empty index returns [] gracefully
# ---------------------------------------------------------------------------

def test_answer_query_empty_index(monkeypatch):
    """
    When the FAISS index is empty, search() returns [] and answer_query()
    returns the 'no logs' graceful message instead of raising an exception.
    """
    monkeypatch.setattr(ai, "get_embedding", _stub_embedding)

    # Index is empty (reset by autouse fixture)
    results = vector_store.search("any question", k=5)
    assert results == [], f"Expected [] on empty index, got {results}"

    # Mimic what the API route does when source_ids is empty
    answer = ai.answer_query("any question", [])
    assert "no logs" in answer.lower() or "not been ingested" in answer.lower(), (
        f"Unexpected graceful message: {answer}"
    )


# ---------------------------------------------------------------------------
# Test 5 — summarize_incident prompt contains MITRE technique and affected IP
# ---------------------------------------------------------------------------

def test_summarize_incident_prompt_content(monkeypatch):
    """
    summarize_incident() must build a prompt that includes the MITRE technique
    ID and the affected IP, then delegate to generate_chat_response.
    """
    captured = {}

    def fake_chat_response(prompt: str, context: str = "") -> str:
        captured["prompt"] = prompt
        captured["context"] = context
        return "Mock AI threat summary."

    monkeypatch.setattr(ai, "generate_chat_response", fake_chat_response)

    incident = _make_incident(
        mitre_technique="T1110",
        mitre_tactic="Credential Access",
        affected_ip="10.0.0.5",
    )
    related = [
        _make_entry(301, "Failed login for user admin from 10.0.0.5", "WARNING"),
        _make_entry(302, "Failed login for user admin from 10.0.0.5", "WARNING"),
    ]

    result = ai.summarize_incident(incident, related)

    assert result == "Mock AI threat summary.", f"Unexpected return value: {result}"
    assert "T1110" in captured["prompt"], "MITRE technique T1110 missing from prompt"
    assert "10.0.0.5" in captured["prompt"], "Affected IP missing from prompt"
    assert "Credential Access" in captured["prompt"], "MITRE tactic missing from prompt"
