import os
import time
from pathlib import Path
from app.database import SessionLocal
from app.models import LogFile, LogEntry, Incident

WATCH_DIR = Path(__file__).resolve().parent / "ingestion_watch"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_DIR = WATCH_DIR / TEST_USER_ID
TEST_LOG_FILE = TEST_USER_DIR / "test_folder_watcher.log"

# Mock log contents: 6 failed logins (brute force trigger) and 1 SQL Injection
MOCK_LOG_LINES = [
    # 6 failed logins within seconds
    '2026-07-01 12:00:00 WARNING Failed login for user hacker_user from 203.0.113.50',
    '2026-07-01 12:00:10 WARNING Failed login for user hacker_user from 203.0.113.50',
    '2026-07-01 12:00:20 WARNING Failed login for user hacker_user from 203.0.113.50',
    '2026-07-01 12:00:30 WARNING Failed login for user hacker_user from 203.0.113.50',
    '2026-07-01 12:00:40 WARNING Failed login for user hacker_user from 203.0.113.50',
    '2026-07-01 12:00:50 WARNING Failed login for user hacker_user from 203.0.113.50',
    # 1 SQL Injection attempt
    '2026-07-01 12:01:00 CRITICAL SQL injection attempt: GET /login?id=1 UNION SELECT username, password FROM users from 198.51.100.22',
]

def verify_watcher():
    print("Starting Folder Watcher Integration Verification...")
    
    # Ensure the per-user watch subdirectory exists (files dropped directly
    # into WATCH_DIR, with no user subfolder, are now ignored by the watcher
    # since there'd be no user to attribute them to — see app/watcher.py).
    TEST_USER_DIR.mkdir(parents=True, exist_ok=True)

    # Write the mock log file (should trigger the watchdog event handler)
    print(f"Dropping mock log file into watch directory: {TEST_LOG_FILE.relative_to(WATCH_DIR)}")
    with open(TEST_LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(MOCK_LOG_LINES) + "\n")
        
    print("Waiting 10 seconds for watcher to detect, parse, and process the file...")
    time.sleep(10)
    
    # Query database to verify pipeline execution
    db = SessionLocal()
    try:
        # 1. Check LogFile record
        log_file = db.query(LogFile).filter(LogFile.filename == TEST_LOG_FILE.name).first()
        if not log_file:
            print("[FAIL] Watcher did not create a LogFile database record.")
            return False
            
        print(f"[OK] LogFile database record found: ID={log_file.id}, Status='{log_file.status}', Uploaded By='{log_file.uploaded_by}'")
        assert log_file.uploaded_by == TEST_USER_ID, f"Expected uploaded_by='{TEST_USER_ID}', got '{log_file.uploaded_by}'"
        assert log_file.status == "completed", f"Expected status='completed', got '{log_file.status}'"
        
        # 2. Check LogEntry records
        entries_count = db.query(LogEntry).filter(LogEntry.file_id == log_file.id).count()
        print(f"[OK] LogEntries parsed and saved to database: {entries_count} entries.")
        assert entries_count == len(MOCK_LOG_LINES), f"Expected {len(MOCK_LOG_LINES)} parsed entries, got {entries_count}"
        
        # 3. Check Incident records
        incidents = db.query(Incident).filter(Incident.log_file_id == log_file.id).all()
        print(f"[OK] Incidents generated: {len(incidents)} incidents.")
        
        # We expect 2 incidents: 1 brute force (high) and 1 SQL injection (critical)
        assert len(incidents) == 2, f"Expected 2 incidents, got {len(incidents)}"
        
        brute_force = next((i for i in incidents if i.rule_name == "Brute force login"), None)
        sql_inject = next((i for i in incidents if i.rule_name == "SQL/XSS injection signature"), None)
        
        assert brute_force is not None, "Brute force login incident missing"
        assert brute_force.severity == "HIGH", f"Expected brute force severity HIGH, got {brute_force.severity}"
        assert brute_force.mitre_technique == "T1110", f"Expected MITRE T1110, got {brute_force.mitre_technique}"
        print(f"[OK] Brute force incident verified: MITRE {brute_force.mitre_technique} ({brute_force.severity})")
        
        assert sql_inject is not None, "SQL Injection incident missing"
        assert sql_inject.severity == "CRITICAL", f"Expected SQL injection severity CRITICAL, got {sql_inject.severity}"
        assert sql_inject.mitre_technique == "T1190", f"Expected MITRE T1190, got {sql_inject.mitre_technique}"
        print(f"[OK] SQL Injection incident verified: MITRE {sql_inject.mitre_technique} ({sql_inject.severity})")
        
        print("[SUCCESS] Folder watcher verification completed successfully!")
        return True
        
    except AssertionError as ae:
        print(f"[FAIL] Assertion failed: {ae}")
        return False
    except Exception as e:
        print(f"[FAIL] Error querying database: {e}")
        return False
    finally:
        db.close()
        # Clean up the dropped file
        if TEST_LOG_FILE.exists():
            os.remove(TEST_LOG_FILE)
            print("Cleaned up mock log file from watch directory.")

if __name__ == "__main__":
    import sys
    success = verify_watcher()
    sys.exit(0 if success else 1)
