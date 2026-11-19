"""Client-credentials auth: exchange a client id + secret for a short-lived JWT.

Deliberately no passlib/bcrypt: log-anomaly-platform incident #3 was passlib's
import-time self-test crashing on modern bcrypt. Client secrets here are
service credentials compared in constant time, not user passwords.
"""

from __future__ import annotations

import hmac
import time

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def verify_client(settings: Settings, client_id: str, client_secret: str) -> bool:
    expected = settings.clients.get(client_id)
    if expected is None:
        # Compare anyway so unknown ids take the same time as wrong secrets.
        hmac.compare_digest(client_secret, client_secret)
        return False
    return hmac.compare_digest(expected.encode(), client_secret.encode())


def issue_token(settings: Settings, client_id: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = {"sub": client_id, "iat": int(now), "exp": int(now) + settings.jwt_ttl_s}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(settings: Settings, token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc
    client_id = payload.get("sub")
    if client_id not in settings.clients:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown client")
    return client_id


def current_client(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(request.app.state.settings, creds.credentials)
