import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded (override any empty system variables)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_current_user
from .database import SessionLocal, get_db
from .doc_processor import process_document_task
from .processor import process_log_file_task
from .supabase import delete_file, fetch_file_bytes, upload_to_supabase
from .watcher import start_watcher, stop_watcher
from . import ai, models, rag, summarizer, vector_store

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

    # The watch-folder feature needs real filesystem access to the backend
    # host, which only makes sense in local dev — on a hosted deployment
    # there's no one who can "drop a file into" the container's disk, so
    # it's off by default in production and only enabled explicitly.
    watcher_enabled = os.getenv("ENABLE_WATCHER", "true").lower() != "false"
    observer = start_watcher() if watcher_enabled else None
    try:
        yield
    finally:
        if observer:
            stop_watcher(observer)


app = FastAPI(
    title="Enterprise Log Monitoring & Threat Detection Platform API",
    description="API for ingesting logs, detecting threats, and querying logs via RAG",
    version="0.1.0",
    lifespan=lifespan,
)

# Per-IP rate limiting on every endpoint (SlowAPIMiddleware applies
# default_limits to any route without its own @limiter.limit decorator;
# expensive Gemini/upload endpoints keep their stricter per-route limits).
# Brute-force protection for authentication is separate: auth.py locks an IP
# out for 15 minutes after 5 failed token validations.
# Counters live in-process by default; point RATE_LIMIT_STORAGE_URI at a
# shared store (e.g. redis://host:6379) if this ever runs multi-instance so
# limits are enforced globally instead of per-worker.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    storage_uri=os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"),
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Reject oversized request bodies before they're read. Slightly above
# MAX_UPLOAD_BYTES to leave room for multipart framing overhead.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
_MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # nosniff stops browsers MIME-guessing JSON/uploads into executable
    # types; DENY blocks framing (clickjacking); the API never needs to
    # send a Referer anywhere. HSTS is ignored over plain-HTTP localhost
    # and kicks in automatically on the TLS-terminated deployment.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


@app.middleware("http")
async def reject_oversized_requests(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large."})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
    return await call_next(request)


# Configure CORS. allow_origins=["*"] combined with allow_credentials=True is
# invalid per the CORS spec (browsers reject credentialed wildcard
# responses), so origins are an explicit allowlist instead — defaulting to
# the local Vite dev server, overridable via a comma-separated
# ALLOWED_ORIGINS env var for deployed frontends.
# Added after the rate-limit/size middleware so CORS runs outermost and 429/413
# responses still carry CORS headers the browser will accept.
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


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "log-threat-detection-api",
    }


@app.get("/")
def read_root():
    return {"message": "Welcome to the Enterprise Log Monitoring & Threat Detection Platform API"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.get("/api/v1/users/me", response_model=CurrentUser)
def read_current_user(current_user: CurrentUser = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------

LOG_UPLOAD_EXTENSIONS = {".log", ".txt", ".csv", ".tsv", ".json", ".ndjson"}
DOCUMENT_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".log", ".csv", ".tsv", ".json",
                              ".xml", ".yaml", ".yml", ".md", ".ndjson"}


def _validate_upload(file: UploadFile, allowed_extensions: set[str]) -> None:
    """Rejects uploads with disallowed extensions or bodies over MAX_UPLOAD_BYTES."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(sorted(allowed_extensions))}",
        )

    # Size of the spooled upload without loading it into memory.
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
        )
    if size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")


# ---------------------------------------------------------------------------
# Log upload
# ---------------------------------------------------------------------------

class LogFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_url: str
    status: str
    uploaded_by: str
    uploaded_at: datetime


@app.post("/api/v1/logs/upload", response_model=LogFileOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("20/minute")
def upload_log_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_upload(file, LOG_UPLOAD_EXTENSIONS)
    file_url = upload_to_supabase(file)

    log_file = models.LogFile(
        filename=file.filename,
        file_url=file_url,
        status="processing",
        uploaded_by=current_user.id,
    )
    db.add(log_file)
    db.commit()
    db.refresh(log_file)

    # Use a dedicated session for the background task since it outlives this request's db session.
    background_tasks.add_task(process_log_file_task, log_file.id, SessionLocal())

    return log_file


@app.get("/api/v1/logs", response_model=list[LogFileOut])
def list_log_files(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists log files uploaded by the current user, most recent first."""
    return (
        db.query(models.LogFile)
        .filter(models.LogFile.uploaded_by == current_user.id)
        .order_by(models.LogFile.uploaded_at.desc())
        .all()
    )


def _owned_log_file_or_404(db: Session, current_user: CurrentUser, log_file_id: int) -> models.LogFile:
    log_file = (
        db.query(models.LogFile)
        .filter(models.LogFile.id == log_file_id, models.LogFile.uploaded_by == current_user.id)
        .first()
    )
    if not log_file:
        raise HTTPException(status_code=404, detail=f"Log file {log_file_id} not found.")
    return log_file


@app.delete("/api/v1/logs/{log_file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log_file(
    log_file_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deletes a log file and its entries/incidents (cascade, see models.py),
    plus its underlying stored file (delete_file — a Supabase Storage
    object or a local_storage/ file). Any FAISS vectors already embedded
    for this file are left in place, unlike the stored file — they become
    unreachable dead weight rather than active stale data, since every
    consumer (rag.py, the /query and /chat endpoints) resolves a vector
    match's id against the LogEntry table and silently drops matches that
    no longer exist there.
    """
    log_file = _owned_log_file_or_404(db, current_user, log_file_id)
    delete_file(log_file.file_url)
    db.delete(log_file)
    db.commit()


@app.post("/api/v1/logs/{log_file_id}/retry", response_model=LogFileOut)
def retry_log_file(
    log_file_id: int,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-runs ingestion for a log file stuck in status='failed'."""
    log_file = _owned_log_file_or_404(db, current_user, log_file_id)
    if log_file.status != "failed":
        raise HTTPException(status_code=400, detail=f"Log file {log_file_id} is not in a failed state.")

    log_file.status = "processing"
    db.commit()
    db.refresh(log_file)

    background_tasks.add_task(process_log_file_task, log_file.id, SessionLocal())
    return log_file


# ---------------------------------------------------------------------------
# Phase 4 — RAG Query
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class QueryResponse(BaseModel):
    answer: str
    sources: list[int]


@app.post("/api/v1/query", response_model=QueryResponse)
@limiter.limit("10/minute")
def query_logs(
    request: Request,
    body: QueryRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Semantic search over ingested log entries using FAISS + Gemini RAG.
    Returns an AI-generated answer grounded in the top-5 matching log lines,
    together with the source LogEntry IDs used as context. Results are
    restricted to the caller's own log entries (see vector_store.search).
    kind="log" also keeps this log-only endpoint from surfacing DocumentChunk
    matches now that the same index holds uploaded-document chunks too.
    """
    results = vector_store.search(body.question, current_user.id, k=5, kind="log")
    source_ids = [r["id"] for r in results]

    if not source_ids:
        return QueryResponse(
            answer=(
                "No logs have been ingested yet. "
                "Please upload a log file first."
            ),
            sources=[],
        )

    entries = (
        db.query(models.LogEntry)
        .filter(models.LogEntry.id.in_(source_ids))
        .all()
    )

    # Sort the database entries to match the relevance order returned by the similarity search
    entry_map = {e.id: e for e in entries}
    ordered_entries = [entry_map[eid] for eid in source_ids if eid in entry_map]

    answer = ai.answer_query(body.question, ordered_entries)
    return QueryResponse(answer=answer, sources=source_ids)


# ---------------------------------------------------------------------------
# Incidents — listing & AI summaries (prd.md feature #6 — "AI incident
# summaries"). Summaries are generated automatically at ingestion time in
# processor.py via app.summarizer; resummarize_incident() below is the sole
# on-demand path for (re)generating one, so there's a single summarization
# implementation (app.summarizer.summarize_incident) instead of two.
# ---------------------------------------------------------------------------

class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    rule_name: str
    severity: str
    description: str
    mitre_technique: str | None
    mitre_tactic: str | None
    status: str
    summary: str | None
    affected_user: str | None
    affected_ip: str | None
    log_file_id: int | None
    created_at: datetime


class IncidentSummaryResponse(BaseModel):
    incident_id: int
    summary: str


def _owned_incident_query(db: Session, current_user: CurrentUser):
    """Incidents joined to their LogFile, restricted to the caller's own files."""
    return (
        db.query(models.Incident)
        .join(models.LogFile, models.Incident.log_file_id == models.LogFile.id)
        .filter(models.LogFile.uploaded_by == current_user.id)
    )


INCIDENT_MAX_LIMIT = 100


@app.get("/api/v1/incidents", response_model=list[IncidentOut])
def list_incidents(
    limit: int | None = None,
    offset: int = 0,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lists incidents from log files uploaded by the current user, most recent
    first. *limit*/*offset* are optional — omitting *limit* returns every
    incident (unchanged behavior for existing callers like IncidentTimeline
    and the Dashboard severity chart, both of which need the full set rather
    than one page); pass *limit* to paginate (Dashboard's "Recent Incidents"
    list does this).
    """
    query = _owned_incident_query(db, current_user).order_by(models.Incident.created_at.desc())
    query = query.offset(max(0, offset))
    if limit is not None:
        query = query.limit(max(1, min(limit, INCIDENT_MAX_LIMIT)))
    return query.all()


@app.get("/api/v1/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches a single incident, provided it belongs to one of the caller's own log files."""
    incident = _owned_incident_query(db, current_user).filter(models.Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found.")
    return incident


@app.post("/api/v1/incidents/{incident_id}/resummarize", response_model=IncidentSummaryResponse)
def resummarize_incident(
    incident_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Regenerates an incident's AI summary on demand, using the same
    incident-scoped context builder (entries matching affected_ip/
    affected_user) that runs automatically at ingestion time in
    processor.py.
    """
    incident = _owned_incident_query(db, current_user).filter(models.Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found.")

    summary = summarizer.summarize_incident(db, incident)
    incident.summary = summary
    db.commit()

    return IncidentSummaryResponse(incident_id=incident.id, summary=summary)


# ---------------------------------------------------------------------------
# RAG Investigation Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    file_id: int | None = Field(default=None, ge=1)
    incident_id: int | None = Field(default=None, ge=1)


class ChatResponse(BaseModel):
    answer: str
    sources: list[int]


NO_MATCH_ANSWER = (
    "No matching log data found for this question. "
    "Try rephrasing, or upload a log file first if you haven't yet."
)


@app.post("/api/v1/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
def chat_with_logs(
    request: Request,
    body: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    RAG-powered investigation chat (prd.md: "RAG-powered investigation
    chat", "Chat with previous incidents"). Retrieves the caller's own log
    chunks most relevant to the question — optionally scoped to a specific
    file or incident — then asks Gemini to answer grounded in that
    context. Skips the LLM call entirely when nothing matches, rather than
    prompting with empty context.
    """
    try:
        context, source_ids = rag.retrieve_context(
            db,
            question=body.question,
            user_id=current_user.id,
            file_id=body.file_id,
            incident_id=body.incident_id,
        )
    except rag.IncidentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not source_ids:
        return ChatResponse(answer=NO_MATCH_ANSWER, sources=[])

    answer = ai.generate_chat_response(body.question, context)
    return ChatResponse(answer=answer, sources=source_ids)


# ---------------------------------------------------------------------------
# Log Search (prd.md feature #8 — "search by IP, user, hostname or event ID")
# ---------------------------------------------------------------------------

SEARCH_DEFAULT_LIMIT = 100
SEARCH_MAX_LIMIT = 500


class LogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: int
    timestamp: datetime | None
    severity: str
    ip_address: str | None
    user_name: str | None
    hostname: str | None
    event_id: str | None
    message: str


@app.get("/api/v1/logs/search", response_model=list[LogEntryOut])
def search_logs(
    ip: str | None = Query(default=None, max_length=64),
    user: str | None = Query(default=None, max_length=256),
    hostname: str | None = Query(default=None, max_length=256),
    event_id: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, max_length=32),
    file_id: int | None = Query(default=None, ge=1),
    limit: int = SEARCH_DEFAULT_LIMIT,
    offset: int = 0,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Plain SQL-filtered log search (prd.md: "search by IP, user, hostname or
    event ID") — distinct from the semantic /api/v1/query and /api/v1/chat
    endpoints. Filters are ANDed together and results are restricted to
    log files uploaded by the caller. At least one filter is required;
    without one this would be an unbounded scan of the user's whole log
    history rather than a search.
    """
    if not any([ip, user, hostname, event_id, severity, file_id]):
        raise HTTPException(
            status_code=400,
            detail="At least one of ip, user, hostname, event_id, severity, or file_id is required.",
        )

    limit = max(1, min(limit, SEARCH_MAX_LIMIT))
    offset = max(0, offset)

    query = (
        db.query(models.LogEntry)
        .join(models.LogFile, models.LogEntry.file_id == models.LogFile.id)
        .filter(models.LogFile.uploaded_by == current_user.id)
    )

    if ip:
        query = query.filter(models.LogEntry.ip_address == ip)
    if user:
        query = query.filter(models.LogEntry.user_name == user)
    if hostname:
        query = query.filter(models.LogEntry.hostname == hostname)
    if event_id:
        query = query.filter(models.LogEntry.event_id == event_id)
    if severity:
        query = query.filter(models.LogEntry.severity == severity)
    if file_id:
        query = query.filter(models.LogEntry.file_id == file_id)

    return (
        query.order_by(models.LogEntry.timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


MAX_IDS_PER_REQUEST = 200


def _parse_ids_param(ids: str) -> list[int]:
    """Parses a comma-separated id list, rejecting malformed or oversized input."""
    try:
        id_list = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be a comma-separated list of integers.")
    if len(id_list) > MAX_IDS_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"At most {MAX_IDS_PER_REQUEST} ids per request.")
    return id_list


@app.get("/api/v1/logs/entries", response_model=list[LogEntryOut])
def get_log_entries(
    ids: str = Query(max_length=2000),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Resolves a comma-separated list of LogEntry ids (e.g. ?ids=1,2,3) back
    into full log content. This exists specifically to resolve the raw
    `sources: number[]` ids returned by POST /api/v1/chat and
    /api/v1/query into renderable citations — those endpoints don't
    attach timestamp/message to each source id, and GET
    /api/v1/logs/search can't be reused for this since it filters by
    field value, not by an id list. Results are restricted to log files
    uploaded by the caller; entries owned by another user, or nonexistent
    ids, are silently omitted rather than erroring. The response order is
    not guaranteed to match *ids* — callers should key results by id.
    """
    id_list = _parse_ids_param(ids)
    if not id_list:
        return []

    return (
        db.query(models.LogEntry)
        .join(models.LogFile, models.LogEntry.file_id == models.LogFile.id)
        .filter(models.LogFile.uploaded_by == current_user.id)
        .filter(models.LogEntry.id.in_(id_list))
        .all()
    )


# ---------------------------------------------------------------------------
# Document Q&A — PDF upload, library, and citation resolution
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
    _validate_upload(file, DOCUMENT_UPLOAD_EXTENSIONS)
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
    """Deletes a document, its chunks (cascade, see models.py), and its stored file — see delete_log_file's docstring re: stale FAISS vectors."""
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
    ids: str = Query(max_length=2000),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Resolves a comma-separated list of DocumentChunk ids (e.g. ?ids=1,2,3)
    back into full chunk text. Document chunk ids share the same FAISS
    index as LogEntry ids, so this is the document-mode counterpart to
    GET /api/v1/logs/entries used to resolve /api/v1/chat citations.
    """
    id_list = _parse_ids_param(ids)
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
