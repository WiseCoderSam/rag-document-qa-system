# Product Requirements Document
# Enterprise Log Monitoring & Threat Detection Platform

## Goal
A free, AI-powered SOC-style platform that ingests application, server and security logs, detects suspicious activity, and lets users investigate incidents using Retrieval-Augmented Generation (RAG).

## Target Users
- Students
- SOC Analysts
- Security Engineers
- Developers

## Core Features
1. User authentication
2. Upload log files (CSV, TXT, JSON, EVTX exported JSON)
3. Real-time log ingestion
4. Rule-based threat detection
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
-> Embeddings (BAAI/bge-small-en-v1.5)
-> FAISS Index
-> Retrieval
-> Ollama (Llama 3.1/Qwen)
-> Source-backed answer

## Detection Rules
- Brute force login
- Impossible travel
- Privilege escalation
- Port scanning
- Multiple failed logins
- Suspicious PowerShell
- Malware indicators
- Credential dumping
- Ransomware patterns

## Non-functional Requirements
- Query <3 seconds
- Role-based access
- Docker support
- Horizontal-ready architecture

## Tech Stack
See tech.md

## Free Services
- Next.js
- FastAPI
- Supabase Free
- Upstash Redis Free
- Ollama
- FAISS
- Docker
- Vercel
- Render Free
- Grafana OSS
- Prometheus

## Resume Highlights
- Full-stack architecture
- AI + RAG
- Vector search
- Threat detection
- Dashboard
- Authentication
- Docker
- CI/CD
- Production-ready design

## Future Enhancements
- Sigma rules
- YARA integration
- Suricata logs
- Zeek logs
- Multi-tenant organizations
- Email/Slack alerts
- SIEM connectors
