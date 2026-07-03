import os
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from dotenv import load_dotenv

from pathlib import Path

# Ensure environment variables are loaded (override any empty system variables)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")

bearer_scheme = HTTPBearer(auto_error=False)

class CurrentUser(BaseModel):
    id: str
    email: str

# Create a JWK client if SUPABASE_URL is configured (used for ES256 verification)
jwk_client = None
if SUPABASE_URL:
    jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    try:
        jwk_client = jwt.PyJWKClient(jwks_url)
    except Exception as e:
        print(f"Warning: Failed to initialize JWK client: {e}")

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """
    Validates the Supabase-issued JWT from the Authorization header and
    returns the authenticated user's id (UUID) and email.
    Supports both ES256 (Supabase cloud) and HS256 (local mock tests).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = credentials.credentials

    try:
        # Inspect token header to detect the signing algorithm
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg")

        if alg == "ES256":
            if not jwk_client:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="JWK client not initialized (SUPABASE_URL missing)",
                )
            # Retrieve public key from Supabase JWKS endpoint
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
            )
        elif alg == "HS256":
            # Fall back to symmetric verification for local tests
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token algorithm: {alg}",
            )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {e}",
        )

    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing required claims",
        )

    return CurrentUser(id=user_id, email=email)
