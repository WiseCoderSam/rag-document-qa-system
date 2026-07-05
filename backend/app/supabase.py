import os
import uuid
from pathlib import Path
import httpx
from fastapi import UploadFile
from supabase import create_client, Client
from dotenv import load_dotenv

# Ensure environment variables are loaded (override any empty system variables)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
BUCKET_NAME = os.getenv("SUPABASE_STORAGE_BUCKET", "logs")

supabase_client: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")

# Ensure local storage fallback directory exists
LOCAL_STORAGE_DIR = Path("local_storage")
LOCAL_STORAGE_DIR.mkdir(exist_ok=True)

def upload_to_supabase(file: UploadFile) -> str:
    """
    Uploads an incoming file to the public "logs" bucket in Supabase Storage
    and returns its public URL. If Supabase is not configured or the upload
    fails for any reason, the file is saved locally under local_storage/ and
    the local path is returned instead.
    """
    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_content = file.file.read()

    if supabase_client:
        try:
            supabase_client.storage.from_(BUCKET_NAME).upload(
                path=unique_filename,
                file=file_content,
                file_options={"content-type": file.content_type or "application/octet-stream"}
            )
            return supabase_client.storage.from_(BUCKET_NAME).get_public_url(unique_filename)
        except Exception as e:
            print(f"Supabase upload failed ({e}). Falling back to local storage.")

    # Fallback to local file storage
    local_path = LOCAL_STORAGE_DIR / unique_filename
    with open(local_path, "wb") as f:
        f.write(file_content)
    return str(local_path.resolve())


def fetch_file_bytes(file_url: str) -> bytes:
    """
    Retrieves raw file bytes from either a Supabase Storage public URL or a
    local filesystem path (the local_storage/ fallback) — the read-side
    counterpart to upload_to_supabase(). Used by the document retry
    endpoint in main.py, which needs to re-read a previously uploaded
    file's contents.
    """
    if file_url.startswith("http://") or file_url.startswith("https://"):
        response = httpx.get(file_url, timeout=30)
        response.raise_for_status()
        return response.content

    return Path(file_url).read_bytes()


def delete_file(file_url: str) -> None:
    """
    Best-effort removal of a previously stored file — the delete-side
    counterpart to upload_to_supabase(). Called by main.py's DELETE
    endpoint before removing the Document row, so a deleted row
    doesn't leave its underlying file (a Supabase Storage object, or a
    local_storage/ file when Supabase wasn't configured/available at
    upload time) as permanent orphaned dead weight. Swallows failures
    (e.g. object already gone) rather than raising, since a delete
    request should still succeed even if cleanup can't confirm the file
    was there.
    """
    try:
        if file_url.startswith("http://") or file_url.startswith("https://"):
            if supabase_client:
                object_path = file_url.split(f"/{BUCKET_NAME}/", 1)[-1]
                supabase_client.storage.from_(BUCKET_NAME).remove([object_path])
        else:
            Path(file_url).unlink(missing_ok=True)
    except Exception as e:
        print(f"Warning: failed to delete stored file at {file_url}: {e}")
