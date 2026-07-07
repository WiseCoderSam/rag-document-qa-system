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

## Deployment

The frontend and backend deploy to different kinds of platforms, because they have different runtime needs — the frontend is static/stateless, the backend needs an always-on process (in-process background jobs for log/document processing) and a real database.

- **Frontend → [Vercel](https://vercel.com).** Import the repo, set the project root to `frontend/`, and set these environment variables: `VITE_API_URL` (your deployed backend's URL), `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`. Vercel auto-detects the Vite build; no extra config needed.
- **Backend → [Render](https://render.com)** (or Railway/Fly.io — anywhere that runs a long-lived Docker container). This repo includes `render.yaml`: import it as a [Render Blueprint](https://dashboard.render.com/blueprints) and it provisions the service from `backend/Dockerfile` automatically. You still need to paste in the secrets yourself (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_JWT_SECRET`, `GEMINI_API_KEY`, `ALLOWED_ORIGINS`) via the Render dashboard.
- **Database → Supabase Postgres**, not the local SQLite fallback. Free hosting tiers (Render's included) don't guarantee persistent disk across redeploys/restarts, so a SQLite file would silently lose data — use your Supabase project's Postgres connection string (Project Settings → Database → Connection string → URI) as `DATABASE_URL` instead, and run `alembic upgrade head` against it once before first use.

## Demo mode

The auth page can show a one-click **"Explore the live demo"** button so visitors (e.g. recruiters) can browse the console with pre-loaded incident data, without signing up. To enable it:

1. **Create the demo account**: in the Supabase dashboard (Authentication → Users → Add user), create e.g. `demo@yourdomain.com` with a password, checking "Auto Confirm User" — or sign up through the app and confirm the email.
2. **Seed it with sample data**: `backend/sample_data/` contains a crafted security log (a coherent brute-force → privilege-escalation → credential-dumping attack that triggers every detection rule) and an incident-response playbook for document Q&A. Upload them through the real API with:
   ```
   cd backend
   python seed_demo.py --email demo@yourdomain.com --password <password> --api-url https://your-api.onrender.com
   ```
   (Omit `--api-url` to seed a locally running backend.) Re-running skips files that are already uploaded.
3. **Show the button**: set `VITE_DEMO_EMAIL` and `VITE_DEMO_PASSWORD` in the frontend's environment (Vercel env vars, or `.env.local` locally). These are baked into the public bundle by design — the demo account is public. The button only renders when both are set.

Note: the demo account is a normal account — visitors can delete the seeded files or upload their own. If that happens, just re-run the seed script.

## Current Architecture

This section describes what's actually implemented, as opposed to the original stretch-goal plan in `tech.md`/`prd.md`.

- **Database**: SQLAlchemy against `DATABASE_URL` (defaults to a local SQLite file for zero-setup local dev). In production this should point at Supabase Postgres instead — see "Deployment" above — Supabase is otherwise used for Auth and Storage.
- **Background processing**: FastAPI `BackgroundTasks` (in-process), not a separate task queue. There is no Celery/Redis dependency.
- **Vector search**: a single in-process FAISS `IndexFlatIP`, persisted to disk. This is a single-instance design — it does not support running multiple backend replicas against a shared index.
- **AI**: Google Gemini (`gemini-embedding-001` for embeddings, `gemini-2.5-flash` for chat/summarization), not a locally-hosted model. This means AI features require an internet connection and a Gemini API key.
- **Monitoring**: none of Grafana/Prometheus/Sentry are integrated. Logging is via `print()`/stdout.

## Known Limitations

- The FAISS index and SQLite database are both single-process/single-file — this is a dev/portfolio-scale setup, not a horizontally-scaled one.
- Detection rules currently cover brute-force login, SQL/XSS injection signatures, privilege escalation, suspicious PowerShell, and credential-dumping keyword matches. Broader coverage (impossible travel, port scanning, ransomware patterns, Sigma/YARA integration) is not yet implemented.
