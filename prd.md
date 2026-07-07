# Product Requirements Document
# Enterprise Log Monitoring & Threat Detection Platform

> Status: this document mixes shipped features with the original stretch-goal plan. "Core Features" and "AI Pipeline" below reflect what's implemented; anything not implemented is listed explicitly under "Future Enhancements." See `tech.md` for the as-built stack.

## Goal
An AI-powered SOC-style platform that ingests application, server and security logs, detects suspicious activity, and lets users investigate incidents using Retrieval-Augmented Generation (RAG). AI features run against the Gemini API (cloud), not a local model — see "Future Enhancements" for a local-model option.

## Target Users
- Students
- SOC Analysts
- Security Engineers
- Developers

## Core Features
1. User authentication
2. Upload log files — line-delimited JSON, RFC3164 syslog, and free-form text/auth logs are parsed and field-extracted; CSV and EVTX-exported JSON are not yet supported (frontend currently accepts `.log`/`.txt`)
3. Rule-based threat detection
5. RAG-powered investigation chat
6. AI incident summaries
7. MITRE ATT&CK technique mapping
8. Search by IP, user, hostname or event ID
9. Severity dashboard
10. Export PDF/CSV reports
11. Incident timeline
12. Chat with previous incidents

## AI Pipeline
Logs
-> Parsing
-> Normalization
-> Chunking
-> Embeddings (Gemini `gemini-embedding-001`)
-> FAISS Index (single-instance, in-process)
-> Retrieval
-> Gemini (`gemini-2.5-flash`)
-> Source-backed answer

## Detection Rules (implemented)
- Brute force login
- SQL/XSS injection signatures
- Privilege escalation
- Suspicious PowerShell
- Credential dumping keyword matches

## Non-functional Requirements
- Docker support (Dockerfiles + docker-compose provided)
- Role-based access: not implemented — auth currently distinguishes authenticated vs. unauthenticated, not roles/permissions within an account
- Query <3 seconds: not measured/enforced
- Horizontal-ready architecture: not met — FAISS index and SQLite are both single-process/single-file (see tech.md "Known Limitations" in README.md)

## Tech Stack
See tech.md

## Resume Highlights (accurate as of current implementation)
- Full-stack architecture (FastAPI + React/TypeScript)
- AI + RAG (Gemini embeddings + chat, source-cited answers)
- Vector search (FAISS)
- Rule-based threat detection
- Dashboard + incident timeline
- JWT-based authentication (Supabase Auth)
- Docker
- CI/CD (GitHub Actions: backend pytest + frontend lint/build/Vitest, on every push/PR)
- Automated tests: backend (pytest) and frontend (Vitest + React Testing Library)

## Future Enhancements
- Local-model AI pipeline (Ollama + Llama 3.1/Qwen + sentence-transformers) as an alternative to the Gemini API
- Celery + Redis for real background job processing (replacing in-process BackgroundTasks)
- Supabase Postgres + pgvector as the primary database and vector store (replacing SQLite + in-process FAISS) for horizontal scalability
- Additional detection rules: impossible travel, port scanning, multiple failed logins across users (password spraying), malware indicators, ransomware patterns
- Sigma rules
- YARA integration
- Suricata logs
- Zeek logs
- Multi-tenant organizations
- Role-based access control
- Email/Slack alerts
- SIEM connectors
- Grafana / Prometheus / Sentry monitoring
