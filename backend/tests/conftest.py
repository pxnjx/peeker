"""Shared fixtures: isolated SQLite DB per test session + fake crawler."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os
import pathlib
import time
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

# Must be set before any app import (settings + engine are created at import time).
_TEST_DB = pathlib.Path(__file__).parent / "_test_peeker.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()
os.environ["PEEKER_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB.as_posix()}"
os.environ["PEEKER_MIN_NAVIGATION_INTERVAL_S"] = "0"
os.environ["PEEKER_WORKER_CONCURRENCY"] = "2"
os.environ["PEEKER_LOG_LEVEL"] = "WARNING"
# The API gate reads the same key as production (PEEKER_SESSION_SECRET first). Fixing it
# here means app.auth.signing_key() never sees surrounding developer environments.
os.environ["PEEKER_SESSION_SECRET"] = "test-only-session-signing-key-0123456789"

from app.crawler.base import ReviewData, ScrapeResult  # noqa: E402
from app.db import dispose_engine, init_db, session_factory  # noqa: E402
from app.db.models import Alert, BlockEvent, Business, PerformanceRow, RatingSnapshot, Review  # noqa: E402


def aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite returns naive UTC datetimes; normalize to aware for comparisons."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def signed_session_token(
    *,
    seconds: int = 3600,
    method: str = "password",
    subject: str = "operator",
    secret: str | None = None,
) -> str:
    """Mint a peeker_session value the same way frontend/lib/session.ts does.

    Test-only twin of the TypeScript signer (the backend itself only verifies): if this
    helper and app.auth disagree, the API tests below turn red, which is exactly the
    alarm we want when either side changes the token format.
    """
    from app.auth import TOKEN_VERSION, signing_key

    key = secret or signing_key()
    assert key is not None, "PEEKER_SESSION_SECRET must be set for authenticated API tests"
    expires_at = int(time.time() * 1000) + seconds * 1000
    subject_b64 = base64.urlsafe_b64encode(subject.encode("utf-8")).decode("ascii").rstrip("=")
    body = f"{TOKEN_VERSION}.{method}.{subject_b64}.{expires_at}"
    mac = hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def api_client(app: Any, *, session: Any = "valid", **kwargs: Any) -> AsyncClient:
    """AsyncClient for the ASGI ``app``, pre-armed with a dashboard session cookie.

    session="valid" (default) - a fresh unexpired cookie, the normal case for API tests.
    session=None              - no cookie at all (anonymous).
    session=<str>             - that exact cookie value (forged/expired cases).
    Extra kwargs are passed straight to httpx.AsyncClient.
    """
    if session is None:
        cookies: dict[str, str] = {}
    elif isinstance(session, str) and session != "valid":
        cookies = {"peeker_session": session}
    else:
        assert session == "valid", f"api_client session must be 'valid', None or a token, got {session!r}"
        cookies = {"peeker_session": signed_session_token()}
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies, **kwargs
    )


class FakeCrawler:
    """Deterministic crawler: returns scripted results or raises scripted errors."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.queue: list[ScrapeResult | Exception] = []
        self.default_result = ScrapeResult(
            business_url="https://maps.example/placeholder",
            avg_rating=4.5,
            review_count=10,
            reviews=[
                ReviewData("r1", "Alice", 5.0, "Great!", dt.datetime(2026, 9, 1, tzinfo=dt.UTC)),
            ],
        )

    def script(self, *items: ScrapeResult | Exception) -> None:
        self.queue.extend(items)

    async def scrape(self, url: str) -> ScrapeResult:
        self.calls.append(url)
        if self.queue:
            item = self.queue.pop(0)
            if isinstance(item, Exception):
                raise item
            result = item
        else:
            result = self.default_result
        # Attach the real target URL for assertions.
        return ScrapeResult(
            business_url=url,
            avg_rating=result.avg_rating,
            review_count=result.review_count,
            reviews=result.reviews,
            scraped_at=result.scraped_at,
        )


@pytest.fixture(autouse=True)
async def db():
    """Create a clean schema before each test and wipe all rows afterwards."""
    await init_db()
    yield
    async with session_factory() as s:
        for table in (Alert, BlockEvent, Review, RatingSnapshot, PerformanceRow, Business):
            await s.execute(table.__table__.delete())  # type: ignore[attr-defined]
        await s.commit()


@pytest.fixture()
def crawler() -> FakeCrawler:
    return FakeCrawler()


@pytest.fixture()
async def teardown_engine():
    yield
    await dispose_engine()
