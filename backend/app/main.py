import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded (override any empty system variables)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_current_user
from .database import SessionLocal, get_db
from .doc_processor import process_document_task
from .supabase import delete_file, fetch_file_bytes, upload_to_supabase
from . import ai, models, rag, vector_store

# Schema is managed exclusively by Alembic migrations (run `alembic upgrade
# head` before starting the app) — this used to also call
# models.Base.metadata.create_all() here, but that only creates missing
# tables and never alters existing ones, so it silently masked the fact that
# the documents/document_chunks tables (see alembic/versions/0002_*) had no
# migration for years. Two competing schema-management paths is a correctness
# risk (see alembic/versions/0002_add_documents_and_document_chunks.py's
# docstring); Alembic is now the only one.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load persisted FAISS index (no-op if none exists yet)
    vector_store.load()
    yield


app = FastAPI(
    title="Document Q&A API",
    description="API for uploading documents and asking questions about them via RAG",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS. allow_origins=["*"] combined with allow_credentials=True is
# invalid per the CORS spec (browsers reject credentialed wildcard
# responses), so origins are an explicit allowlist instead — defaulting to
# the local Vite dev server, overridable via a comma-separated
# ALLOWED_ORIGINS env var for deployed frontends.
_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting for endpoints that call the Gemini API or accept uploads —
# unauthenticated per-IP limits (checked before the JWT dependency resolves),
# just enough to stop a single client from exhausting the Gemini free-tier
# quota or hammering the FAISS index/background-task pool.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "document-qa-api",
    }


@app.get("/")
def read_root():
    return {"message": "Welcome to the Document Q&A API"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.get("/api/v1/users/me", response_model=CurrentUser)
def read_current_user(current_user: CurrentUser = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# RAG Q&A Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str
    document_id: int | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[int]


NO_MATCH_ANSWER = (
    "No matching document content found for this question. "
    "Try rephrasing, or upload a document first if you haven't yet."
)


@app.post("/api/v1/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
def chat_with_documents(
    request: Request,
    body: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    RAG-powered document Q&A. Retrieves the caller's own document chunks
    most relevant to the question — optionally scoped to a specific
    document — then asks Gemini to answer grounded in that context. Skips
    the LLM call entirely when nothing matches, rather than prompting with
    empty context.
    """
    try:
        context, source_ids = rag.retrieve_context(
            db,
            question=body.question,
            user_id=current_user.id,
            document_id=body.document_id,
        )
    except rag.DocumentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not source_ids:
        return ChatResponse(answer=NO_MATCH_ANSWER, sources=[])

    answer = ai.generate_chat_response(body.question, context)
    return ChatResponse(answer=answer, sources=source_ids)


# ---------------------------------------------------------------------------
# Document Q&A — upload, library, and citation resolution
# ---------------------------------------------------------------------------

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_url: str
    page_count: int | None
    status: str
    uploaded_by: str
    uploaded_at: datetime


class DocumentChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    chunk_index: int
    text: str


@app.post("/api/v1/documents/upload", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("20/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Read the bytes now — FastAPI closes the upload stream after this
    # request returns, so the background task can't read from `file` later.
    file_bytes = await file.read()
    await file.seek(0)
    file_url = upload_to_supabase(file)

    document = models.Document(
        filename=file.filename,
        file_url=file_url,
        status="processing",
        uploaded_by=current_user.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # Use a dedicated session for the background task since it outlives this request's db session.
    background_tasks.add_task(process_document_task, document.id, file_bytes, SessionLocal())

    return document


@app.get("/api/v1/documents", response_model=list[DocumentOut])
def list_documents(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Document)
        .filter(models.Document.uploaded_by == current_user.id)
        .order_by(models.Document.uploaded_at.desc())
        .all()
    )


def _owned_document_or_404(db: Session, current_user: CurrentUser, document_id: int) -> models.Document:
    document = (
        db.query(models.Document)
        .filter(models.Document.id == document_id, models.Document.uploaded_by == current_user.id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    return document


@app.delete("/api/v1/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deletes a document, its chunks (cascade, see models.py), and its stored
    file (delete_file — a Supabase Storage object or a local_storage/ file).
    Any FAISS vectors already embedded for this document are left in place,
    unlike the stored file — they become unreachable dead weight rather than
    active stale data, since every consumer (rag.py, the /chat endpoint)
    resolves a vector match's id against the DocumentChunk table and
    silently drops matches that no longer exist there.
    """
    document = _owned_document_or_404(db, current_user, document_id)
    delete_file(document.file_url)
    db.delete(document)
    db.commit()


@app.post("/api/v1/documents/{document_id}/retry", response_model=DocumentOut)
def retry_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-runs processing for a document stuck in status='failed'."""
    document = _owned_document_or_404(db, current_user, document_id)
    if document.status != "failed":
        raise HTTPException(status_code=400, detail=f"Document {document_id} is not in a failed state.")

    file_bytes = fetch_file_bytes(document.file_url)

    document.status = "processing"
    db.commit()
    db.refresh(document)

    background_tasks.add_task(process_document_task, document.id, file_bytes, SessionLocal())
    return document


@app.get("/api/v1/documents/chunks", response_model=list[DocumentChunkOut])
def get_document_chunks_by_ids(
    ids: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Resolves a comma-separated list of DocumentChunk ids (e.g. ?ids=1,2,3)
    back into full chunk text. This exists specifically to resolve the raw
    `sources: number[]` ids returned by POST /api/v1/chat into renderable
    citations — that endpoint doesn't attach text to each source id.
    Results are restricted to documents uploaded by the caller; chunks
    owned by another user, or nonexistent ids, are silently omitted rather
    than erroring. The response order is not guaranteed to match *ids* —
    callers should key results by id.
    """
    try:
        id_list = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be a comma-separated list of integers.")

    if not id_list:
        return []

    return (
        db.query(models.DocumentChunk)
        .join(models.Document, models.DocumentChunk.document_id == models.Document.id)
        .filter(models.Document.uploaded_by == current_user.id)
        .filter(models.DocumentChunk.id.in_(id_list))
        .all()
    )


@app.get("/api/v1/documents/{document_id}/chunks", response_model=list[DocumentChunkOut])
def get_document_chunks(
    document_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = (
        db.query(models.Document)
        .filter(models.Document.id == document_id)
        .filter(models.Document.uploaded_by == current_user.id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    return (
        db.query(models.DocumentChunk)
        .filter(models.DocumentChunk.document_id == document_id)
        .order_by(models.DocumentChunk.chunk_index)
        .all()
    )
