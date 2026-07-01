# Enterprise Log Monitoring & Threat Detection Platform

A free, AI-powered SOC-style platform that ingests application, server, and security logs, detects suspicious activity, and enables investigations using Retrieval-Augmented Generation (RAG).

## Repository Structure

- `frontend/` - Vite (React, TypeScript, Tailwind CSS, shadcn/ui) application.
- `backend/` - FastAPI (Python, SQLAlchemy, Celery, FAISS, Ollama) application.

## Prerequisites

- [Node.js](https://nodejs.org/) (v18+)
- [Python](https://www.python.org/) (v3.10+)
- [Ollama](https://ollama.com/) (running locally with `llama3.1` or `qwen2.5` pulled)
- [Supabase Account](https://supabase.com/) (for PostgreSQL database, Storage, and Auth)

## Quick Start

### 1. Backend Setup
1. Navigate to the `backend/` directory.
2. Create a virtual environment: `python -m venv venv`.
3. Activate it: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Mac/Linux).
4. Install dependencies: `pip install -r requirements.txt`.
5. Create a `.env` file based on `.env.example`.
6. Start the FastAPI server: `uvicorn app.main:app --reload`.

### 2. Frontend Setup
1. Navigate to the `frontend/` directory.
2. Install dependencies: `npm install`.
3. Create a `.env.local` file based on `.env.example`.
4. Start the dev server: `npm run dev`.
