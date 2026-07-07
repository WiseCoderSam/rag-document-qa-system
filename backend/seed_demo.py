"""
Seeds a demo account with sample data by uploading backend/sample_data/*
through the real API — exactly what a user clicking "Upload" would trigger.

Going through the API (rather than inserting rows directly) matters: the
target backend runs the full ingestion pipeline itself, so its own FAISS
index gets the embeddings and its own Gemini key generates the incident
summaries. Point --api-url at the deployed backend to seed production, or
leave the default to seed a locally running one.

Usage:
    python seed_demo.py --email demo@example.com --password <password> \
        [--api-url https://your-api.onrender.com]

The demo account must already exist in Supabase with a confirmed email
(create it via the app's sign-up flow, or in the Supabase dashboard with
"Auto Confirm User" checked). SUPABASE_URL and SUPABASE_KEY are read from
backend/.env (any key works here — the password grant only needs a
publishable/anon-level key).

Re-running is safe: files already uploaded for the account are skipped by
filename, so a wiped backend (e.g. after a Render redeploy clears the FAISS
index) can be re-seeded by deleting the demo files in the UI and running
this again.
"""

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"

LOG_SAMPLES = ["demo_security.log"]
DOCUMENT_SAMPLES = ["incident_response_playbook.md"]


def sign_in(supabase_url: str, supabase_key: str, email: str, password: str) -> str:
    response = httpx.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        json={"email": email, "password": password},
        headers={"apikey": supabase_key},
        timeout=30,
    )
    if response.status_code != 200:
        sys.exit(
            f"Sign-in failed ({response.status_code}): {response.text}\n"
            "Check the demo account exists in Supabase and its email is confirmed."
        )
    return response.json()["access_token"]


def existing_filenames(api_url: str, token: str, endpoint: str) -> set[str]:
    response = httpx.get(
        f"{api_url}{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return {item["filename"] for item in response.json()}


def upload(api_url: str, token: str, endpoint: str, path: Path) -> None:
    with path.open("rb") as f:
        response = httpx.post(
            f"{api_url}{endpoint}",
            files={"file": (path.name, f)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
    response.raise_for_status()
    print(f"  uploaded {path.name} -> {endpoint} (id={response.json()['id']})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo account with sample data.")
    parser.add_argument("--email", required=True, help="Demo account email")
    parser.add_argument("--password", required=True, help="Demo account password")
    parser.add_argument(
        "--api-url",
        default=os.getenv("API_URL", "http://localhost:8000"),
        help="Backend to seed (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_KEY", "")
    if not supabase_url or not supabase_key:
        sys.exit("SUPABASE_URL and SUPABASE_KEY must be set in backend/.env")

    api_url = args.api_url.rstrip("/")
    print(f"Signing in as {args.email} against {supabase_url} ...")
    token = sign_in(supabase_url, supabase_key, args.email, args.password)

    print(f"Seeding {api_url} ...")
    logs_present = existing_filenames(api_url, token, "/api/v1/logs")
    for name in LOG_SAMPLES:
        if name in logs_present:
            print(f"  skipping {name} (already uploaded)")
        else:
            upload(api_url, token, "/api/v1/logs/upload", SAMPLE_DIR / name)

    docs_present = existing_filenames(api_url, token, "/api/v1/documents")
    for name in DOCUMENT_SAMPLES:
        if name in docs_present:
            print(f"  skipping {name} (already uploaded)")
        else:
            upload(api_url, token, "/api/v1/documents/upload", SAMPLE_DIR / name)

    print(
        "Done. Processing runs in the background on the server — incidents and "
        "chat context should appear within a minute or so."
    )


if __name__ == "__main__":
    main()
