from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded (override any empty system variables)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

from fastapi import BackgroundTasks, Depends, FastAPI, File, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .auth import CurrentUser, get_current_user
from .database import SessionLocal, engine, get_db
from .processor import process_log_file_task
from .supabase import upload_to_supabase
from .watcher import start_watcher, stop_watcher
from . import models

# Create database tables automatically
try:
    models.Base.metadata.create_all(bind=engine)
    print("Database tables initialized successfully.")
except Exception as e:
    print(f"Error initializing database tables: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
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

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "log-threat-detection-api"
    }

@app.get("/")
def read_root():
    return {"message": "Welcome to the Enterprise Log Monitoring & Threat Detection Platform API"}

@app.get("/api/v1/users/me", response_model=CurrentUser)
def read_current_user(current_user: CurrentUser = Depends(get_current_user)):
    return current_user

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
