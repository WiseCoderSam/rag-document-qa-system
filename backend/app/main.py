from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded (override any empty system variables)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_current_user
from .database import SessionLocal, engine, get_db
from .processor import process_log_file_task
from .supabase import upload_to_supabase
from .watcher import start_watcher, stop_watcher
from . import ai, models, rag, summarizer, vector_store

# Create database tables automatically
try:
    models.Base.metadata.create_all(bind=engine)
    print("Database tables initialized successfully.")
except Exception as e:
    print(f"Error initializing database tables: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load persisted FAISS index (no-op if none exists yet)
    vector_store.load()
    observer = start_watcher()
    try:
        yield
    finally:
        stop_watcher(observer)


app = FastAPI(
    title="Enterprise Log Monitoring & Threat Detection Platform API",
    description="API for ingesting logs, detecting threats, and querying logs via RAG",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
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
# Log upload
# ---------------------------------------------------------------------------

class LogFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_url: str
    status: str
    uploaded_by: str


@app.post("/api/v1/logs/upload", response_model=LogFileOut, status_code=status.HTTP_202_ACCEPTED)
def upload_log_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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


# ---------------------------------------------------------------------------
# Phase 4 — RAG Query
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[int]


@app.post("/api/v1/query", response_model=QueryResponse)
def query_logs(
    body: QueryRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Semantic search over ingested log entries using FAISS + Gemini RAG.
    Returns an AI-generated answer grounded in the top-5 matching log lines,
    together with the source LogEntry IDs used as context. Results are
    restricted to the caller's own log entries (see vector_store.search).
    """
    source_ids = vector_store.search(body.question, current_user.id, k=5)

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


@app.get("/api/v1/incidents", response_model=list[IncidentOut])
def list_incidents(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists incidents from log files uploaded by the current user, most recent first."""
    return (
        _owned_incident_query(db, current_user)
        .order_by(models.Incident.created_at.desc())
        .all()
    )


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
    question: str
    file_id: int | None = None
    incident_id: int | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[int]


NO_MATCH_ANSWER = (
    "No matching log data found for this question. "
    "Try rephrasing, or upload a log file first if you haven't yet."
)


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat_with_logs(
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
    ip: str | None = None,
    user: str | None = None,
    hostname: str | None = None,
    event_id: str | None = None,
    severity: str | None = None,
    file_id: int | None = None,
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
