"""Session gate tests: who the API serves, and who gets turned away.

The gate's positive case (a valid signed cookie returns data) is exercised by every
other API test through conftest.api_client. These tests pin down the negative cases:

  * no cookie, forged, expired, wrong-key, unknown-method cookies -> 401, never data
  * legacy two-part cookies (minted before subject ids) still verify
  * /health stays open for probes
  * no signing key configured at all -> fail closed with 503
"""
from __future__ import annotations

from app.auth import session_subject
from app.main import create_app
from tests.conftest import api_client, signed_session_token


def test_session_subject_accepts_valid_token() -> None:
    subject = session_subject(signed_session_token())
    assert subject is not None
    assert (subject.id, subject.method) == ("operator", "password")


def test_session_subject_rejects_garbage() -> None:
    for token in (None, "", "v1.password.only-three.parts", "v1.password.b3BlcmF0b3I.42"):
        assert session_subject(token) is None


def test_session_subject_hmac_is_checked() -> None:
    token = signed_session_token()
    body, _, _ = token.rpartition(".")
    assert session_subject(f"{body}.{'0' * 64}") is None
    assert session_subject(signed_session_token(secret="some-other-key")) is None


def test_session_subject_expiry_is_checked() -> None:
    assert session_subject(signed_session_token(seconds=-1)) is None


def test_session_subject_allows_listed_methods_only() -> None:
    for method in ("password", "google", "email"):
        assert session_subject(signed_session_token(method=method)) is not None
    assert session_subject(signed_session_token(method="admin")) is None


def test_session_subject_accepts_legacy_two_part_cookies() -> None:
    import hashlib
    import hmac
    import time

    from app.auth import signing_key

    key = signing_key()
    assert key is not None
    expires_at = str(int(time.time() * 1000) + 3600_000)
    mac = hmac.new(key.encode(), expires_at.encode(), hashlib.sha256).hexdigest()
    subject = session_subject(f"{expires_at}.{mac}")
    assert subject is not None
    assert (subject.id, subject.method) == ("operator", "password")


async def test_gate_accepts_valid_session_on_data_routes() -> None:
    app = create_app()
    async with api_client(app) as client:
        resp = await client.get("/api/stats")
        assert resp.status_code == 200


async def test_gate_rejects_anonymous_on_read_and_write_routes() -> None:
    app = create_app()
    async with api_client(app, session=None) as client:
        for method, path in (
            ("get", "/api/stats"),
            ("get", "/api/businesses"),
            ("get", "/api/alerts"),
            ("post", "/api/enqueue-all"),
            ("delete", "/api/businesses/999999"),
        ):
            resp = await client.request(method, path)
            assert resp.status_code == 401, f"{method.upper()} {path}"
            assert "detail" in resp.json()


async def test_gate_rejects_forged_and_stale_cookies() -> None:
    app = create_app()
    forged = signed_session_token(secret="some-other-key")
    stale = signed_session_token(seconds=-1)
    strange = signed_session_token(method="admin")
    for token in (forged, stale, strange, "not-a-token"):
        async with api_client(app, session=token) as client:
            resp = await client.get("/api/stats")
            assert resp.status_code == 401, token[:20]


async def test_health_stays_open_without_a_session() -> None:
    app = create_app()
    async with api_client(app, session=None) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200


async def test_gate_fails_closed_without_a_signing_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import app.auth

    monkeypatch.setattr(app.auth, "signing_key", lambda: None)
    async with api_client(app=create_app(), session=None) as client:
        resp = await client.get("/api/stats")
        assert resp.status_code == 503
