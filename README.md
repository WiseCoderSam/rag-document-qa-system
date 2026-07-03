# Enterprise Log Monitoring & Threat Detection Platform

An AI-powered SOC-style platform that ingests application, server, and security logs, detects suspicious activity with rule-based detection, and enables investigations using Retrieval-Augmented Generation (RAG).

## Repository Structure

- `frontend/` - Vite (React, TypeScript, Tailwind CSS, @base-ui/react) application.
- `backend/` - FastAPI (Python, SQLAlchemy, Alembic, FAISS, Google Gemini) application.

## Prerequisites

- [Node.js](https://nodejs.org/) (v18+)
- [Python](https://www.python.org/) (v3.10+)
- [Google Gemini API key](https://ai.google.dev/) — used for embeddings and chat/summarization. Without one, the app still runs but AI features return a "not configured" message and embeddings fall back to zero-vectors.
- [Supabase Account](https://supabase.com/) (for Auth and Storage; the relational database defaults to a local SQLite file — see below)

## Quick Start

### 1. Backend Setup
1. Navigate to the `backend/` directory.
2. Create a virtual environment: `python -m venv venv`.
3. Activate it: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Mac/Linux).
4. Install dependencies: `pip install -r requirements.txt`.
5. Create a `.env` file based on `.env.example` and set at least `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_JWT_SECRET`, and `GEMINI_API_KEY`.
6. Apply database migrations: `alembic upgrade head`.
7. Start the FastAPI server: `uvicorn app.main:app --reload`.

### 2. Frontend Setup
1. Navigate to the `frontend/` directory.
2. Install dependencies: `npm install`.
3. Create a `.env.local` file based on `.env.example`.
4. Start the dev server: `npm run dev`.

## Running Tests

- Backend: `pip install -r backend/requirements-dev.txt`, then `pytest backend/test_parser_rules.py backend/test_rag.py` (the other `backend/test_*.py` files are manual verification scripts meant to be run against a live server, not pytest suites).
- Frontend: `npm run test` from `frontend/`.
- Both run automatically in CI on every push/PR — see `.github/workflows/ci.yml`.

## Current Architecture

This section describes what's actually implemented, as opposed to the original stretch-goal plan in `tech.md`/`prd.md`.

- **Database**: SQLAlchemy against `DATABASE_URL` (defaults to a local SQLite file). Supabase Postgres is not currently wired up as the app database — Supabase is only used for Auth and Storage.
- **Background processing**: FastAPI `BackgroundTasks` (in-process), not a separate task queue. There is no Celery/Redis dependency.
- **Vector search**: a single in-process FAISS `IndexFlatIP`, persisted to disk. This is a single-instance design — it does not support running multiple backend replicas against a shared index.
- **AI**: Google Gemini (`gemini-embedding-001` for embeddings, `gemini-2.5-flash` for chat/summarization), not a locally-hosted model. This means AI features require an internet connection and a Gemini API key.
- **Monitoring**: none of Grafana/Prometheus/Sentry are integrated. Logging is via `print()`/stdout.

## Known Limitations

- The FAISS index and SQLite database are both single-process/single-file — this is a dev/portfolio-scale setup, not a horizontally-scaled one.
- Detection rules currently cover brute-force login, SQL/XSS injection signatures, privilege escalation, suspicious PowerShell, and credential-dumping keyword matches. Broader coverage (impossible travel, port scanning, ransomware patterns, Sigma/YARA integration) is not yet implemented.
