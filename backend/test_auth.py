import os
import jwt
from fastapi import HTTPException

# Configure dummy secret for authentication validation
TEST_SECRET = "test_secret_key"
os.environ["SUPABASE_JWT_SECRET"] = TEST_SECRET

# Import auth modules after setting env variables to ensure it initializes properly
from app.auth import get_current_user, CurrentUser, HTTPAuthorizationCredentials

def run_tests():
    print("Running token validation tests...")
    
    # 1. Test Valid Token
    payload = {
        "sub": "12345678-abcd-1234-abcd-123456789abc",
        "email": "test@example.com",
        "aud": "authenticated"
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    
    try:
        user = get_current_user(credentials)
        assert user.id == "12345678-abcd-1234-abcd-123456789abc", "User ID mismatch"
        assert user.email == "test@example.com", "Email mismatch"
        print("[OK] Test 1: Valid token validation passed.")
    except Exception as e:
        print(f"[FAIL] Test 1 failed: {e}")
        return False
        
    # 2. Test Invalid Token (wrong secret)
    bad_token = jwt.encode(payload, "wrong_secret", algorithm="HS256")
    credentials_bad = HTTPAuthorizationCredentials(scheme="Bearer", credentials=bad_token)
    
    try:
        get_current_user(credentials_bad)
        print("[FAIL] Test 2 failed: Expected HTTPException was not raised.")
        return False
    except HTTPException as e:
        assert e.status_code == 401, f"Expected 401 status, got {e.status_code}"
        assert "Invalid authentication token" in e.detail, f"Unexpected error detail: {e.detail}"
        print("[OK] Test 2: Invalid token signature rejected correctly.")
    except Exception as e:
        print(f"[FAIL] Test 2 failed: Unexpected exception {e}")
        return False
        
    # 3. Test Missing Claims
    payload_missing = {
        "sub": "12345678-abcd-1234-abcd-123456789abc",
        "aud": "authenticated"
    }
    token_missing = jwt.encode(payload_missing, TEST_SECRET, algorithm="HS256")
    credentials_missing = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_missing)
    
    try:
        get_current_user(credentials_missing)
        print("[FAIL] Test 3 failed: Expected HTTPException for missing claims was not raised.")
        return False
    except HTTPException as e:
        assert e.status_code == 401, f"Expected 401 status, got {e.status_code}"
        assert "Token is missing required claims" in e.detail, f"Unexpected error detail: {e.detail}"
        print("[OK] Test 3: Token with missing claims rejected correctly.")
    except Exception as e:
        print(f"[FAIL] Test 3 failed: Unexpected exception {e}")
        return False

    print("All tests passed successfully!")
    return True

if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
