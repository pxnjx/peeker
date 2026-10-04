"""APScheduler dispatcher: promotes due businesses to QUEUED so workers pick them up."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from .db import checkpoint_and_optimize, session_factory
from .db.base import utcnow
from .db.models import Business, BusinessStatus

log = logging.getLogger(__name__)


async def dispatch_once() -> int:
    """Promote parked (cooldown expired) and due idle/backoff businesses to QUEUED."""
    now = utcnow()
    promoted = 0
    async with session_factory() as s:
        parked = (
            await s.execute(
                select(Business).where(
                    Business.status == BusinessStatus.PARKED.value,
                    Business.parked_until.is_not(None),
                    Business.parked_until <= now,
                )
            )
        ).scalars()
        for b in parked:
            b.status = BusinessStatus.QUEUED.value
            b.next_due_at = now
            promoted += 1

        due = (
            await s.execute(
                select(Business).where(
                    Business.status.in_([BusinessStatus.IDLE.value, BusinessStatus.BACKOFF.value]),
                    Business.next_due_at.is_not(None),
                    Business.next_due_at <= now,
                )
            )
        ).scalars()
        for b in due:
            b.status = BusinessStatus.QUEUED.value
            promoted += 1

        # Queued but pulled forward in time (e.g. never scheduled) → make due now.
        await s.execute(
            update(Business)
            .where(Business.status == BusinessStatus.QUEUED.value, Business.next_due_at.is_(None))
            .values(next_due_at=now)
        )
        await s.commit()
    if promoted:
        log.info("dispatch promoted %d businesses to QUEUED", promoted)
    return promoted


async def wal_maintenance() -> None:
    """Keep the WAL file bounded and the planner's statistics fresh (SQLite only)."""
    await checkpoint_and_optimize()


def build_scheduler(interval_s: int = 15) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(dispatch_once, "interval", seconds=interval_s, id="dispatch", replace_existing=True)
    # journal_size_limit only bites at the next checkpoint, so without this an idle-ish app would
    # carry its largest WAL until shutdown. coalesce + max_instances keep a slow pass from stacking.
    scheduler.add_job(
        wal_maintenance,
        "interval",
        minutes=10,
        id="wal_maintenance",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
