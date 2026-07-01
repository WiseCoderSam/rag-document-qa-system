import os
import time
import jwt
import httpx
from dotenv import load_dotenv
from pathlib import Path

# Load the actual JWT secret from the project root .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "test_secret_key")

# 1. Generate a mock JWT token for authentication signed with the loaded secret
payload = {
    "sub": "12345678-abcd-1234-abcd-123456789abc",
    "email": "test@example.com",
    "aud": "authenticated"
}
token = jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")

# 2. Target server URL (must be running)
URL = "http://127.0.0.1:8000"

def verify_upload():
    print("Starting Log Upload & Background Task Verification...")
    
    headers = {"Authorization": f"Bearer {token}"}
    filename = "auth_failure_investigation.log"
    file_content = b"2026-07-01 10:00:00 ERROR Failed login attempt for user admin from 10.0.0.5\n"
    files = {"file": (filename, file_content, "text/plain")}

    try:
        # Send upload POST request
        print(f"Sending POST request to {URL}/api/v1/logs/upload...")
        response = httpx.post(f"{URL}/api/v1/logs/upload", files=files, headers=headers)
        
        if response.status_code != 202:
            print(f"[FAIL] Expected status 202 Accepted, got {response.status_code}")
            print(f"Response content: {response.text}")
            return False
            
        res_data = response.json()
        print(f"[OK] Upload endpoint returned HTTP 202 Accepted immediately.")
        print(f"File Metadata - ID: {res_data['id']}, Filename: {res_data['filename']}, Status: {res_data['status']}")
        
        # Verify initial status is "processing"
        assert res_data['status'] == "processing", f"Expected initial status 'processing', got '{res_data['status']}'"
        
        # 3. Wait for background task to complete (processor.py has a 5s sleep simulation)
        print("Waiting 6 seconds for background task to parse log and update status...")
        time.sleep(6)
        
        # 4. Check the SQLite database directly to verify status updated to "completed"
        # Import local DB modules (ensure test runs from backend/ directory)
        from app.database import SessionLocal
        from app.models import LogFile
        
        db = SessionLocal()
        try:
            db_record = db.query(LogFile).filter(LogFile.id == res_data['id']).first()
            if not db_record:
                print("[FAIL] LogFile record was not found in the database.")
                return False
                
            print(f"[OK] Database status checked. Current status: '{db_record.status}'")
            assert db_record.status == "completed", f"Expected status 'completed', but got '{db_record.status}'"
            print("[SUCCESS] Manual Verification successful: Background tasks and upload APIs work perfectly!")
            return True
        finally:
            db.close()
            
    except Exception as e:
        print(f"[FAIL] Connection error: {e}")
        print("Please make sure the Uvicorn server is running locally on http://127.0.0.1:8000")
        return False

if __name__ == "__main__":
    import sys
    success = verify_upload()
    sys.exit(0 if success else 1)
