"""End-to-end flow tests: claim → scrape → persist → alerts, plus block/backoff/park."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.crawler.base import DegradedError, ReviewData, ScrapeResult
from app.db import session_factory
from app.db.models import Alert, Business, BusinessStatus, RatingSnapshot, Review
from app.scheduler import utcnow
from app.worker import WorkerPool
from tests.conftest import FakeCrawler, aware


async def _add_business(name: str = "Cafe Alpha", kind: str = "own") -> Business:
    async with session_factory() as s:
        b = Business(
            name=name,
            maps_url="https://maps.google.com/?cid=1",
            kind=kind,
            status=BusinessStatus.QUEUED.value,
            next_due_at=utcnow() - dt.timedelta(seconds=1),
        )
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return b


async def _reload(business_id: int) -> Business | None:
    async with session_factory() as s:
        return await s.get(Business, business_id)


async def _run_one(pool: WorkerPool) -> None:
    """Claim and process exactly one due business (mirrors one worker iteration)."""
    claimed = await pool._claim_one()
    assert claimed is not None, "expected a due queued business to claim"
    await pool._process(claimed)


async def test_successful_scrape_persists_reviews_and_snapshot(crawler: FakeCrawler) -> None:
    b = await _add_business()
    pool = WorkerPool(crawler)
    await _run_one(pool)

    b = await _reload(b.id)
    assert b is not None
    assert b.status == BusinessStatus.IDLE.value
    assert b.consecutive_blocks == 0
    assert b.next_due_at is not None and aware(b.next_due_at) > utcnow()  # type: ignore[arg-type]
    assert crawler.calls == [b.maps_url]

    async with session_factory() as s:
        reviews = list((await s.execute(select(Review).where(Review.business_id == b.id))).scalars())
        snaps_q = select(RatingSnapshot).where(RatingSnapshot.business_id == b.id)
        snapshots = list((await s.execute(snaps_q)).scalars())
    assert len(reviews) == 1
    assert reviews[0].google_review_id == "r1"
    assert len(snapshots) == 1
    assert snapshots[0].avg_rating == 4.5


async def test_rer_scrape_dedupes_reviews(crawler: FakeCrawler) -> None:
    b = await _add_business()
    pool = WorkerPool(crawler)
    await _run_one(pool)

    # Re-queue and scrape again with the same review + one new.
    async with session_factory() as s:
        row = await s.get(Business, b.id)
        assert row is not None
        row.status = BusinessStatus.QUEUED.value
        row.next_due_at = utcnow() - dt.timedelta(seconds=1)
        await s.commit()
    crawler.script(
        ScrapeResult(
            business_url="x",
            avg_rating=4.6,
            review_count=11,
            reviews=[
                ReviewData("r1", "Alice", 5.0, "Great!", None),
                ReviewData("r2", "Bob", 4.0, "Nice", None),
            ],
        )
    )
    await _run_one(pool)

    async with session_factory() as s:
        reviews = list((await s.execute(select(Review).where(Review.business_id == b.id))).scalars())
        snaps_q = select(RatingSnapshot).where(RatingSnapshot.business_id == b.id)
        snapshots = list((await s.execute(snaps_q)).scalars())
    assert {r.google_review_id for r in reviews} == {"r1", "r2"}
    assert len(reviews) == 2  # no duplicate of r1
    assert len(snapshots) == 2  # both scrapes recorded for trends


async def test_rescrape_updates_truncated_review_text(crawler: FakeCrawler) -> None:
    """A re-scrape that recovers the expanded body must overwrite the "…" preview text."""
    b = await _add_business()
    pool = WorkerPool(crawler)
    await _run_one(pool)

    async with session_factory() as s:
        row = await s.get(Business, b.id)
        assert row is not None
        row.status = BusinessStatus.QUEUED.value
        row.next_due_at = utcnow() - dt.timedelta(seconds=1)
        await s.commit()
    crawler.script(
        ScrapeResult(
            business_url="x",
            avg_rating=4.5,
            review_count=1,
            reviews=[
                ReviewData(
                    "r1",
                    "Alice",
                    5.0,
                    "Great service and the staff was very helpful with my account setup today",
                    None,
                ),
            ],
        )
    )
    await _run_one(pool)

    async with session_factory() as s:
        reviews = list((await s.execute(select(Review).where(Review.business_id == b.id))).scalars())
    assert len(reviews) == 1
    assert "very helpful" in reviews[0].text


async def test_degraded_scrape_backs_off_without_writing(crawler: FakeCrawler) -> None:
    """A soft-degraded page must not persist a 0/0 snapshot or fire a false alert."""
    b = await _add_business()
    crawler.script(DegradedError("no rating summary and no review cards"))
    pool = WorkerPool(crawler)
    await _run_one(pool)

    reloaded = await _reload(b.id)
    assert reloaded is not None
    assert reloaded.status == BusinessStatus.BACKOFF.value
    assert reloaded.consecutive_blocks == 0  # backoff, not a hard block
    assert reloaded.next_due_at is not None and aware(reloaded.next_due_at) > utcnow()  # type: ignore[arg-type]

    async with session_factory() as s:
        snapshots = list(
            (await s.execute(select(RatingSnapshot).where(RatingSnapshot.business_id == b.id))).scalars()
        )
        alerts = list((await s.execute(select(Alert).where(Alert.business_id == b.id))).scalars())
    assert snapshots == []  # no avg=0/count=0 garbage
    assert alerts == []  # no false rating-drop alert
