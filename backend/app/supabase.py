import os
import uuid
from pathlib import Path
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
