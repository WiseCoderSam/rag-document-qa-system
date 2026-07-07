import os
import time
from collections import deque

import jwt
from fastapi import Depends, HTTPException, Request, status
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

# Brute-force lockout for token validation: after AUTH_FAILURE_LIMIT failed
# authentication attempts from one IP within AUTH_FAILURE_WINDOW_SECONDS,
# further attempts are rejected with 429 until the window slides past.
# In-process only (resets on restart, per-worker) — adequate for a
# single-instance deployment; move to Redis if this ever runs multi-instance.
AUTH_FAILURE_LIMIT = 5
AUTH_FAILURE_WINDOW_SECONDS = 15 * 60
_failed_auth_attempts: dict[str, deque[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _prune_failures(ip: str) -> deque[float]:
    attempts = _failed_auth_attempts.setdefault(ip, deque())
    cutoff = time.monotonic() - AUTH_FAILURE_WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if not attempts:
        # Don't let one-off failures from many IPs grow the dict forever.
        _failed_auth_attempts.pop(ip, None)
    return attempts


def _check_auth_lockout(ip: str) -> None:
    if len(_prune_failures(ip)) >= AUTH_FAILURE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Try again in 15 minutes.",
        )


def _record_auth_failure(ip: str) -> None:
    _failed_auth_attempts.setdefault(ip, deque()).append(time.monotonic())


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
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """
    Validates the Supabase-issued JWT from the Authorization header and
    returns the authenticated user's id (UUID) and email.
    Supports both ES256 (Supabase cloud) and HS256 (local mock tests).
    Repeated failures from one IP trigger a 15-minute lockout (see
    _check_auth_lockout above).
    """
    ip = _client_ip(request)
    _check_auth_lockout(ip)

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
            # Fall back to symmetric verification for local tests.
            # Refuse outright when no secret is configured — verifying
            # against the "" default would let anyone forge a valid token
            # by signing it with an empty key.
            if not SUPABASE_JWT_SECRET:
                _record_auth_failure(ip)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="HS256 tokens are not accepted by this server",
                )
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            _record_auth_failure(ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token algorithm: {alg}",
            )
    except jwt.PyJWTError:
        # Deliberately generic: echoing the library error would tell an
        # attacker why their forged token failed.
        _record_auth_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id or not email:
        _record_auth_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing required claims",
        )

    return CurrentUser(id=user_id, email=email)
