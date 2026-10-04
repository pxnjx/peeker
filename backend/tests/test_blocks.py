"""Block handling: backoff progression and parking after max consecutive blocks."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.config import get_settings
from app.crawler.base import BlockedError
from app.db import session_factory
from app.db.models import BlockEvent, Business, BusinessStatus
from app.scheduler import dispatch_once, utcnow
from app.worker import WorkerPool
from tests.conftest import FakeCrawler, aware
from tests.test_flow import _add_business, _reload, _run_one


async def test_block_sets_backoff_and_records_event(crawler: FakeCrawler) -> None:
    settings = get_settings()
    b = await _add_business()
    crawler.script(BlockedError("captcha"))
    pool = WorkerPool(crawler)
    await _run_one(pool)

    b = await _reload(b.id)
    assert b is not None
    assert b.status == BusinessStatus.BACKOFF.value
    assert b.consecutive_blocks == 1
    assert b.next_due_at is not None
    # Backoff should be the first configured step (5 min default), not due immediately.
    assert b.next_due_at is not None
    assert aware(b.next_due_at) > utcnow() + dt.timedelta(minutes=4)  # type: ignore[arg-type]

    async with session_factory() as s:
        events = list((await s.execute(select(BlockEvent).where(BlockEvent.business_id == b.id))).scalars())
    assert len(events) == 1
    assert events[0].page_url == b.maps_url
    assert settings.max_consecutive_blocks >= 3


async def test_parks_after_max_consecutive_blocks(crawler: FakeCrawler) -> None:
    settings = get_settings()
    b = await _add_business()
    pool = WorkerPool(crawler)

    for i in range(settings.max_consecutive_blocks):
        async with session_factory() as s:
            row = await s.get(Business, b.id)
            assert row is not None
            # Force due-now so the claim picks it up each round.
            row.status = (
                BusinessStatus.QUEUED.value
                if row.status != BusinessStatus.PARKED.value
                else row.status
            )
            row.next_due_at = utcnow() - dt.timedelta(seconds=1)
            await s.commit()
        crawler.script(BlockedError("captcha"))
        if i < settings.max_consecutive_blocks:
            if (await _reload(b.id)).status == BusinessStatus.PARKED.value:  # type: ignore[union-attr]
                break
            await _run_one(pool)

    b = await _reload(b.id)
    assert b is not None
    assert b.status == BusinessStatus.PARKED.value
    assert b.consecutive_blocks == settings.max_consecutive_blocks
    assert b.parked_until is not None and aware(b.parked_until) > utcnow()  # type: ignore[arg-type]


async def test_success_after_block_resets_consecutive_blocks(crawler: FakeCrawler) -> None:
    b = await _add_business()
    pool = WorkerPool(crawler)
    crawler.script(BlockedError("captcha"))
    await _run_one(pool)

    async with session_factory() as s:
        row = await s.get(Business, b.id)
        assert row is not None
        row.status = BusinessStatus.QUEUED.value
        row.next_due_at = utcnow() - dt.timedelta(seconds=1)
        await s.commit()
    await _run_one(pool)

    b = await _reload(b.id)
    assert b is not None
    assert b.status == BusinessStatus.IDLE.value
    assert b.consecutive_blocks == 0


async def test_scheduler_promotes_due_businesses(crawler: FakeCrawler) -> None:
    async with session_factory() as s:
        b = Business(
            name="Due Biz",
            maps_url="https://maps.google.com/?cid=2",
            kind="own",
            status=BusinessStatus.IDLE.value,
            next_due_at=utcnow() - dt.timedelta(minutes=1),
        )
        s.add(b)
        await s.commit()
        await s.refresh(b)

    promoted = await dispatch_once()
    assert promoted == 1

    b = await _reload(b.id)
    assert b is not None
    assert b.status == BusinessStatus.QUEUED.value
