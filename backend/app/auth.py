"""Session gate for the JSON API.

The dashboard UI is gated by ``frontend/app/dashboard/layout.tsx``, but the API that UI
talks to was wide open: any process that could reach the port could list every business,
read every review and ``DELETE /api/businesses/{id}`` without ever knowing the dashboard
password. Loopback binding and CORS narrow that (browsers only, only this machine) but
neither is an authorisation check, and a stray ``--host 0.0.0.0`` or a reverse proxy
would expose all of it. This module makes the signed cookie - not the network location
of the request - decide what may be read or written.

``frontend/lib/session.ts`` is the reference implementation and the two must agree
byte for byte:

    token = v1.<method>.<b64url(subject id)>.<expiresAt ms>.<hex hmac>
    hmac  = HMAC-SHA256(key, "v1.<method>.<b64url(subject id)>.<expiresAt ms>")
    key   = PEEKER_SESSION_SECRET — and only that, so the two agree exactly.

Verification is a single HMAC against a key both sides hold: no session store, no
shared file, and a forged or expired cookie is rejected exactly like a missing one.
Tokens minted before subject ids existed ("expiresAt.mac", two parts) are still
accepted, mirroring the legacy branch in lib/session.ts.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import math
import time
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import APIKeyCookie

from .config import get_settings

TOKEN_VERSION = "v1"
# Mirrors AuthSubject["method"] in lib/session.ts: a token naming any other method is
# treated as forged rather than trusted.
SUBJECT_METHODS = frozenset({"password", "google", "email"})


@dataclass(frozen=True)
class AuthSubject:
    """Who a request belongs to, taken from the verified cookie."""

    id: str
    method: str


def signing_key() -> str | None:
    """The same key lib/session.ts uses, or None when the API cannot verify anything.

    PEEKER_SESSION_SECRET and nothing else. The previous fallback to
    PEEKER_DASHBOARD_PASSWORD let the backend accept cookies signed with a key
    lib/session.ts would never produce (it reads only the secret), and it used a
    human-chosen password as an HMAC key, which is the wrong input for one. The
    frontend fails closed with a 503 when the secret is missing; this side now
    matches instead of quietly widening what it accepts.
    """
    return get_settings().session_secret or None


def _sign(payload: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _decode_subject(part: str) -> str | None:
    """Inverse of encodeSubject() in lib/session.ts. None on malformed input."""
    try:
        padded = part + "=" * (-len(part) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def session_subject(token: str | None, now_ms: int | None = None) -> AuthSubject | None:
    """The subject a cookie belongs to, or None when it is absent, forged or expired."""
    key = signing_key()
    if not key or not token:
        return None

    parts = token.split(".")
    if len(parts) == 5 and parts[0] == TOKEN_VERSION:
        _, method, id_part, expires_at, mac = parts
        if method not in SUBJECT_METHODS:
            return None
        subject_id = _decode_subject(id_part)
        if not subject_id or not expires_at or not mac:
            return None
        body = ".".join(parts[:4])
    elif len(parts) == 2:
        # Legacy `expiresAt.mac` cookies, signed over the expiry alone.
        expires_at, mac = parts
        subject_id, method = "operator", "password"
        body = expires_at
        if not expires_at or not mac:
            return None
    else:
        return None

    # compare_digest on the hex digests: constant time, and length mismatch is False
    # rather than an exception the way Node's timingSafeEqual would need guarding.
    if not hmac.compare_digest(_sign(body, key), mac):
        return None

    try:
        # JS writes String(Date.now()), but Number() also accepts "1e13", so parse as a
        # float and reject non-finite to stay in step with verifySession()'s Number check.
        expiry = float(expires_at)
    except ValueError:
        return None
    if not math.isfinite(expiry):
        return None

    now = int(time.time() * 1000) if now_ms is None else now_ms
    if expiry <= now:
        return None

    return AuthSubject(id=subject_id, method=method)


def _cookie_scheme() -> APIKeyCookie:
    # Declared as a security scheme so Swagger's Authorize dialog accepts a pasted
    # dashboard cookie; auto_error is off so this module owns the 401 wording.
    return APIKeyCookie(name=get_settings().session_cookie_name, auto_error=False)


session_cookie = _cookie_scheme()


async def require_session(cookie: str | None = Security(session_cookie)) -> AuthSubject:
    """Router dependency: 200 for a signed-in dashboard, 401 for everything else.

    Fails closed - a backend with no signing key refuses all data routes rather than
    defaulting to open, the same way the login route returns 503 with no password set.
    """
    if signing_key() is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "API auth is not configured: set PEEKER_SESSION_SECRET in backend/.env to the "
                "same value as frontend/.env.local. Refusing to serve data with no way to "
                "verify a session."
            ),
        )
    subject = session_subject(cookie)
    if subject is None:
        raise HTTPException(
            status_code=401,
            detail="A signed dashboard session is required. Sign in at http://localhost:3001/login.",
        )
    return subject
