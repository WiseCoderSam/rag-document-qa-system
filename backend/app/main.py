from contextlib import asynccontextmanager
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
from . import ai, models, vector_store

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
    together with the source LogEntry IDs used as context.
    """
    source_ids = vector_store.search(body.question, k=5)

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

    answer = ai.answer_query(body.question, entries)
    return QueryResponse(answer=answer, sources=source_ids)


# ---------------------------------------------------------------------------
# Phase 4 — Incident Summarization
# ---------------------------------------------------------------------------

class IncidentSummaryResponse(BaseModel):
    incident_id: int
    summary: str


@app.post("/api/v1/incidents/{incident_id}/summarize", response_model=IncidentSummaryResponse)
def summarize_incident(
    incident_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate (or regenerate) an AI threat summary for a given Incident.
    Pulls up to 20 related LogEntry rows for context, calls Gemini, and
    persists the summary back to Incident.summary.
    """
    incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found.")

    related_entries = (
        db.query(models.LogEntry)
        .filter(models.LogEntry.file_id == incident.log_file_id)
        .limit(20)
        .all()
        if incident.log_file_id
        else []
    )

    summary = ai.summarize_incident(incident, related_entries)

    incident.summary = summary
    db.commit()

    return IncidentSummaryResponse(incident_id=incident.id, summary=summary)
