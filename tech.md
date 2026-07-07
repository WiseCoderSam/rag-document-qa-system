# Enterprise Log Monitoring & Threat Detection Platform - Tech Stack

This reflects what is actually implemented today. See "Future Enhancements" in `prd.md` for stretch goals that are not yet built.

## Frontend
- Vite (React 19, TypeScript)
- Tailwind CSS v4
- @base-ui/react (unstyled primitives, styled shadcn-style)
- Recharts
- react-markdown (renders AI responses/summaries; deliberately does not render raw HTML, so log content quoted back by the LLM can't execute as script)

## Backend
- FastAPI (Python)
- SQLAlchemy + Alembic (migrations)
- Pydantic / pydantic-settings
- Uvicorn
- FastAPI `BackgroundTasks` for async processing (no separate task queue)

## Database
- Defaults to local SQLite (`DATABASE_URL`, see `backend/.env.example`)
- Supabase Postgres is available via the same `DATABASE_URL` setting but is not the default — Supabase is currently only used for Auth and Storage, not as the app's relational database

## AI / Detection
- Google Gemini API:
  - `gemini-embedding-001` for embeddings (768-dim, pinned via `output_dimensionality`)
  - `gemini-2.5-flash` for chat, RAG answers, and incident summarization
- FAISS (`faiss-cpu`, `IndexFlatIP`) — in-process, single-instance vector search
- Rule-based detection (`backend/app/rules.py`): regex/threshold rules over parsed log fields, not a local ML model

## Log Processing
- PyMuPDF (`fitz`) for PDF text extraction
- Python `logging` / stdout

## Authentication
- Supabase Auth (JWT, ES256 via JWKS in production, HS256 fallback for local/test tokens)

## Storage
- Supabase Storage, with a local-filesystem fallback (`backend/local_storage/`) when Supabase isn't configured or the upload fails

## Deployment
- Docker (Dockerfiles for both `frontend/` and `backend/`, plus `docker-compose.yml`)
- GitHub Actions CI (`.github/workflows/ci.yml`): runs backend pytest and frontend lint/build/test on every push/PR

## Monitoring
- None currently. Grafana/Prometheus/Sentry are aspirational — see prd.md.

## Features (implemented)
- Log ingestion (file upload)
- Rule-based threat detection (brute force, SQL/XSS injection signatures, privilege escalation, suspicious PowerShell, credential dumping)
- AI incident summaries
- RAG-powered investigation chat (scoped to a file, an incident, or unscoped)
- Semantic log search + structured field search (IP/user/hostname/event ID)
- Document (PDF/text) upload and RAG chat over documents
- Severity dashboard
- Incident timeline
- CSV/PDF export of incidents and search results
- User authentication

## Estimated Cost
Development: ₹0 (Gemini free tier + Supabase free tier)
