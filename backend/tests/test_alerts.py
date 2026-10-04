"""Alert engine: rating drops (urgent + normal), review bursts, dedupe window."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.alerts import evaluate_alerts, utcnow
from app.db import session_factory
from app.db.models import Alert, AlertKind, Business, RatingSnapshot, Review


async def _business() -> Business:
    async with session_factory() as s:
        b = Business(name="Alert Co", maps_url="https://maps.google.com/?cid=9", kind="own")
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return b


async def _snapshot(business_id: int, avg: float, taken_at: dt.datetime) -> RatingSnapshot:
    async with session_factory() as s:
        snap = RatingSnapshot(business_id=business_id, avg_rating=avg, review_count=10, taken_at=taken_at)
        s.add(snap)
        await s.commit()
        await s.refresh(snap)
        return snap


async def test_urgent_rating_drop_alert() -> None:
    b = await _business()
    prev = await _snapshot(b.id, 4.8, utcnow() - dt.timedelta(hours=6))
    async with session_factory() as s:
        biz = await s.get(Business, b.id)
        assert biz is not None
        created = await evaluate_alerts(s, biz, prev, new_avg=4.3, new_count=10)
        await s.commit()
    assert len(created) == 1
    assert created[0].kind == AlertKind.RATING_DROP_URGENT.value
    assert created[0].urgent is True


async def test_normal_rating_drop_alert() -> None:
    b = await _business()
    prev = await _snapshot(b.id, 4.8, utcnow() - dt.timedelta(days=3))
    async with session_factory() as s:
        biz = await s.get(Business, b.id)
        assert biz is not None
        created = await evaluate_alerts(s, biz, prev, new_avg=4.6, new_count=10)
        await s.commit()
    assert len(created) == 1
    assert created[0].kind == AlertKind.RATING_DROP.value
    assert created[0].urgent is False


async def test_no_alert_for_small_or_old_drop() -> None:
    b = await _business()
    # Older than the urgent window: normal drop threshold (0.1) applies but 30d > 7d window.
    prev = await _snapshot(b.id, 4.7, utcnow() - dt.timedelta(days=30))
    async with session_factory() as s:
        biz = await s.get(Business, b.id)
        assert biz is not None
        created = await evaluate_alerts(s, biz, prev, new_avg=4.6, new_count=10)
        await s.commit()
    assert created == []  # 30 days old → outside the 7d normal window


async def test_dedupe_skips_repeat_alerts() -> None:
    b = await _business()
    prev = await _snapshot(b.id, 4.9, utcnow() - dt.timedelta(hours=2))
    async with session_factory() as s:
        biz = await s.get(Business, b.id)
        assert biz is not None
        first = await evaluate_alerts(s, biz, prev, new_avg=4.4, new_count=10)
        await s.commit()
        second = await evaluate_alerts(s, biz, prev, new_avg=4.3, new_count=10)
        await s.commit()
        rows = list((await s.execute(select(Alert).where(Alert.business_id == b.id))).scalars())
    assert len(first) == 1
    assert second == []  # same kind inside dedupe window → skipped
    assert len(rows) == 1


async def test_first_scrape_never_fires_review_burst() -> None:
    """No previous snapshot → the whole history is just the baseline, not a burst."""
    b = await _business()
    async with session_factory() as s:
        for i in range(6):  # ≥ the burst threshold (5)
            s.add(
                Review(
                    business_id=b.id,
                    google_review_id=f"g{i}",
                    author=f"author {i}",
                    rating=4.0,
                    text="nice",
                    review_time=None,
                    first_seen_at=utcnow(),
                )
            )
        await s.commit()
    async with session_factory() as s:
        biz = await s.get(Business, b.id)
        assert biz is not None
        created = await evaluate_alerts(s, biz, None, new_avg=4.5, new_count=6)
        await s.commit()
    assert created == []


async def test_review_burst_fires_after_baseline() -> None:
    b = await _business()
    prev = await _snapshot(b.id, 4.5, utcnow() - dt.timedelta(hours=1))
    async with session_factory() as s:
        for i in range(5):  # first seen after the previous snapshot → counts
            s.add(
                Review(
                    business_id=b.id,
                    google_review_id=f"g{i}",
                    author=f"author {i}",
                    rating=4.0,
                    text="nice",
                    review_time=None,
                    first_seen_at=utcnow(),
                )
            )
        await s.commit()
    async with session_factory() as s:
        biz = await s.get(Business, b.id)
        assert biz is not None
        created = await evaluate_alerts(s, biz, prev, new_avg=4.5, new_count=15)
        await s.commit()
    assert [a.kind for a in created] == [AlertKind.REVIEW_BURST.value]

