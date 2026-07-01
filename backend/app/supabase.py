import os
import uuid
from pathlib import Path
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
BUCKET_NAME = os.getenv("SUPABASE_STORAGE_BUCKET", "logs")

supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")

# Ensure local storage fallback directory exists
LOCAL_STORAGE_DIR = Path("storage")
LOCAL_STORAGE_DIR.mkdir(exist_ok=True)

def upload_log_file(file_content: bytes, filename: str) -> str:
    """
    Uploads file content to Supabase Storage if configured.
    Otherwise, saves to the local backend storage directory.
    Returns the file URL or local file path.
    """
    unique_filename = f"{uuid.uuid4()}_{filename}"

    if supabase_client:
        try:
            # Upload file to the Supabase storage bucket
            supabase_client.storage.from_(BUCKET_NAME).upload(
                path=unique_filename,
                file=file_content,
                file_options={"content-type": "application/octet-stream"}
            )
            # Retrieve the public URL for the uploaded file
            public_url = supabase_client.storage.from_(BUCKET_NAME).get_public_url(unique_filename)
            return public_url
        except Exception as e:
            print(f"Supabase upload failed ({e}). Falling back to local storage.")
            
    # Fallback to local file storage
    local_path = LOCAL_STORAGE_DIR / unique_filename
    with open(local_path, "wb") as f:
        f.write(file_content)
    return str(local_path.resolve())
