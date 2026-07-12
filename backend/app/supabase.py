import os
import re
import uuid
from pathlib import Path
import httpx
from fastapi import UploadFile
from supabase import create_client, Client

# .strip() guards against trailing newlines/spaces pasted into the host's
# env-var dashboard — a bad SUPABASE_KEY silently fails storage auth and
# falls back to local disk (see upload_to_supabase).
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
BUCKET_NAME = os.getenv("SUPABASE_STORAGE_BUCKET", "logs").strip()

supabase_client: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")

# Ensure local storage fallback directory exists
LOCAL_STORAGE_DIR = Path("local_storage")
LOCAL_STORAGE_DIR.mkdir(exist_ok=True)

def _safe_filename(filename: str | None) -> str:
    """
    Strips directory components and non-portable characters from a
    client-supplied filename. Filenames are attacker-controlled input and are
    used to build storage paths — without this, a name like "..\\..\\x" or
    "a/b" could escape local_storage/ or write into other bucket prefixes.
    """
    # Path().name handles "/" everywhere; also split on "\\" for
    # Windows-style separators when the backend runs on POSIX.
    name = Path(filename or "upload").name.split("\\")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    # Cap length so the uuid prefix + name stays a valid path/object key.
    return name[:100] or "upload"


def upload_to_supabase(file: UploadFile) -> str:
    """
    Uploads an incoming file to the Supabase Storage bucket and returns a
    "supabase://<bucket>/<object>" reference (NOT a public URL — the bucket
    should be private; uploaded logs/documents are sensitive user data, and a
    public bucket lets anyone with the URL read them). fetch_file_bytes and
    delete_file resolve this reference through the authenticated Storage API.
    If Supabase is not configured or the upload fails for any reason, the
    file is saved locally under local_storage/ and the local path is
    returned instead.
    """
    unique_filename = f"{uuid.uuid4()}_{_safe_filename(file.filename)}"
    file_content = file.file.read()

    if supabase_client:
        try:
            supabase_client.storage.from_(BUCKET_NAME).upload(
                path=unique_filename,
                file=file_content,
                file_options={"content-type": file.content_type or "application/octet-stream"}
            )
            return f"supabase://{BUCKET_NAME}/{unique_filename}"
        except Exception as e:
            print(f"Supabase upload failed ({e}). Falling back to local storage.")

    # Fallback to local file storage
    local_path = LOCAL_STORAGE_DIR / unique_filename
    with open(local_path, "wb") as f:
        f.write(file_content)
    return str(local_path.resolve())


def _object_path(file_url: str) -> str | None:
    """
    Extracts the Storage object path from either a "supabase://<bucket>/<obj>"
    reference or a legacy public URL (rows written before the bucket went
    private). Returns None if the reference doesn't point at our bucket.
    """
    if file_url.startswith("supabase://"):
        rest = file_url.removeprefix("supabase://")
        bucket, _, obj = rest.partition("/")
        return obj if bucket == BUCKET_NAME and obj else None
    if f"/{BUCKET_NAME}/" in file_url:
        return file_url.split(f"/{BUCKET_NAME}/", 1)[-1].split("?")[0]
    return None


def fetch_file_bytes(file_url: str) -> bytes:
    """
    Retrieves raw file bytes from a "supabase://" Storage reference, a legacy
    Supabase public URL, or a local filesystem path (the local_storage/
    fallback) — the read-side counterpart to upload_to_supabase(). Shared by
    log/document ingestion (processor.py, doc_processor.py) and by the retry
    endpoints in main.py, which all need to re-read a previously uploaded
    file's contents. Storage objects are downloaded through the authenticated
    API so reads keep working once the bucket is private.
    """
    is_http = file_url.startswith("http://") or file_url.startswith("https://")

    if file_url.startswith("supabase://") or is_http:
        object_path = _object_path(file_url)
        if object_path and supabase_client:
            return supabase_client.storage.from_(BUCKET_NAME).download(object_path)
        if is_http:
            # Not one of our bucket objects (or no client) — plain fetch.
            response = httpx.get(file_url, timeout=30)
            response.raise_for_status()
            return response.content
        raise RuntimeError(f"Cannot resolve storage reference {file_url!r}: Supabase client not configured.")

    return Path(file_url).read_bytes()


def delete_file(file_url: str) -> None:
    """
    Best-effort removal of a previously stored file — the delete-side
    counterpart to upload_to_supabase(). Called by main.py's DELETE
    endpoints before removing the LogFile/Document row, so a deleted row
    doesn't leave its underlying file (a Supabase Storage object, or a
    local_storage/ file when Supabase wasn't configured/available at
    upload time) as permanent orphaned dead weight. Swallows failures
    (e.g. object already gone) rather than raising, since a delete
    request should still succeed even if cleanup can't confirm the file
    was there.
    """
    try:
        if file_url.startswith(("supabase://", "http://", "https://")):
            object_path = _object_path(file_url)
            if supabase_client and object_path:
                supabase_client.storage.from_(BUCKET_NAME).remove([object_path])
        else:
            Path(file_url).unlink(missing_ok=True)
    except Exception as e:
        print(f"Warning: failed to delete stored file at {file_url}: {e}")
