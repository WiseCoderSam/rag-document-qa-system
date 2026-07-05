# RAG Document Q&A System

An AI-powered document Q&A app: upload PDFs or text files, then ask questions about them in a chat grounded in your own documents via Retrieval-Augmented Generation (RAG), with citations back to the exact passages used.

## Repository Structure

- `frontend/` - Vite (React, TypeScript, Tailwind CSS, @base-ui/react) application.
- `backend/` - FastAPI (Python, SQLAlchemy, Alembic, FAISS, Google Gemini) application.

## Prerequisites

- [Node.js](https://nodejs.org/) (v18+)
- [Python](https://www.python.org/) (v3.10+)
- [Google Gemini API key](https://ai.google.dev/) — used for embeddings and chat answers. Without one, the app still runs but AI features return a "not configured" message and embeddings fall back to zero-vectors.
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

- Backend: `pip install -r backend/requirements-dev.txt`, then `pytest backend/test_rag.py` (`backend/test_auth.py` is a manual verification script meant to be run directly, not a pytest suite).
- Frontend: `npm run test` from `frontend/`.
- Both run automatically in CI on every push/PR — see `.github/workflows/ci.yml`.

## Deployment

The frontend and backend deploy to different kinds of platforms, because they have different runtime needs — the frontend is static/stateless, the backend needs an always-on process (background document processing) and a real database.

- **Frontend → [Vercel](https://vercel.com).** Import the repo, set the project root to `frontend/`, and set these environment variables: `VITE_API_URL` (your deployed backend's URL), `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`. Vercel auto-detects the Vite build; no extra config needed.
- **Backend → [Render](https://render.com)** (or Railway/Fly.io — anywhere that runs a long-lived Docker container). This repo includes `render.yaml`: import it as a [Render Blueprint](https://dashboard.render.com/blueprints) and it provisions the service from `backend/Dockerfile` automatically. You still need to paste in the secrets yourself (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_JWT_SECRET`, `GEMINI_API_KEY`, `ALLOWED_ORIGINS`) via the Render dashboard.
- **Database → Supabase Postgres**, not the local SQLite fallback. Free hosting tiers (Render's included) don't guarantee persistent disk across redeploys/restarts, so a SQLite file would silently lose data — use your Supabase project's Postgres connection string (Project Settings → Database → Connection string → URI) as `DATABASE_URL` instead, and run `alembic upgrade head` against it once before first use.

## Current Architecture

This section describes what's actually implemented, as opposed to the original stretch-goal plan in `tech.md`/`prd.md` (those documents describe an earlier log-monitoring incarnation of this project and are kept for historical reference only).

- **Database**: SQLAlchemy against `DATABASE_URL` (defaults to a local SQLite file for zero-setup local dev). In production this should point at Supabase Postgres instead — see "Deployment" above — Supabase is otherwise used for Auth and Storage.
- **Background processing**: FastAPI `BackgroundTasks` (in-process), not a separate task queue. There is no Celery/Redis dependency.
- **Vector search**: a single in-process FAISS `IndexFlatIP`, persisted to disk. This is a single-instance design — it does not support running multiple backend replicas against a shared index.
- **AI**: Google Gemini (`gemini-embedding-001` for embeddings, `gemini-2.5-flash` for chat), not a locally-hosted model. This means AI features require an internet connection and a Gemini API key.
- **Monitoring**: none of Grafana/Prometheus/Sentry are integrated. Logging is via `print()`/stdout.

## Known Limitations

- The FAISS index and SQLite database are both single-process/single-file — this is a dev/portfolio-scale setup, not a horizontally-scaled one.
- Chat conversations are not persisted — they live in browser memory and are lost on page reload.
- Citations point at extracted text chunks, not page numbers — there is no in-app document viewer.
