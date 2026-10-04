"""Worker pool: claims QUEUED businesses, scrapes them, persists results, applies backoff."""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import random
import time
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from .alerts import evaluate_alerts
from .config import Settings, get_settings
from .crawler.base import BlockedError, Crawler, ScrapeResult
from .db import session_factory
from .db.base import utcnow
from .db.models import BlockEvent, Business, BusinessStatus, RatingSnapshot, Review

log = logging.getLogger(__name__)


class NavigationGate:
    """Global throttle: at least `min_interval_s` between scrape starts (anti-detect)."""

    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = min_interval_s
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.min_interval_s:
                await asyncio.sleep(self.min_interval_s - delta)
            self._last = time.monotonic()


class WorkerPool:
    def __init__(self, crawler: Crawler, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.crawler = crawler
        self.gate = NavigationGate(self.settings.min_navigation_interval_s)
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._stop.clear()
        n = max(1, self.settings.worker_concurrency)
        self._tasks = [asyncio.create_task(self._worker(i), name=f"peeker-worker-{i}") for i in range(n)]
        log.info("worker pool started with %d workers", n)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks.clear()
        log.info("worker pool stopped")

    # -------------------------------------------------------------------- loop
    async def _worker(self, idx: int) -> None:
        while not self._stop.is_set():
            try:
                claimed = await self._claim_one()
                if claimed is None:
                    await asyncio.sleep(2.0)
                    continue
                await self._process(claimed)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a worker must never die
                log.exception("worker %d: unexpected error; backing off 5s", idx)
                await asyncio.sleep(5.0)

    async def _claim_one(self) -> int | None:
        """Atomically move the oldest due QUEUED business to SCRAPING and return its id."""
        async with session_factory() as s:
            row = (
                await s.execute(
                    select(Business.id)
                    .where(
                        Business.status == BusinessStatus.QUEUED.value,
                        Business.next_due_at.is_not(None),
                        Business.next_due_at <= utcnow(),
                    )
                    .order_by(Business.next_due_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            res = cast(
                "CursorResult[Any]",
                await s.execute(
                    update(Business)
                    .where(Business.id == row, Business.status == BusinessStatus.QUEUED.value)
                    .values(status=BusinessStatus.SCRAPING.value)
                ),
            )
            await s.commit()
            # rowcount 0 → another worker claimed it first: this one backs off, no double scrape.
            return int(row) if res.rowcount == 1 else None

    # ---------------------------------------------------------------- processing
    async def _process(self, business_id: int) -> None:
        async with session_factory() as s:
            business = await s.get(Business, business_id)
            if business is None:
                return
            url = business.maps_url

        await self.gate.wait()
        try:
            result = await self.crawler.scrape(url)
        except BlockedError as exc:
            log.warning("business %d blocked: %s", business_id, exc)
            await self._on_blocked(business_id, url)
        except asyncio.CancelledError:
            # Pool is shutting down: release the claim so the task is retried later.
            await self._reset_to_queued(business_id)
            raise
        except Exception as exc:  # noqa: BLE001 - transient scrape failure → backoff
            log.exception("business %d scrape failed: %s", business_id, exc)
            await self._on_failure(business_id)
        else:
            await self._on_success(business_id, result)

    async def _on_success(self, business_id: int, result: ScrapeResult) -> None:
        async with session_factory() as s:
            business = await s.get(Business, business_id)
            if business is None:
                return
            prev_snapshot = (
                await s.execute(
                    select(RatingSnapshot)
                    .where(RatingSnapshot.business_id == business_id)
                    .order_by(RatingSnapshot.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            # Upsert reviews by (business, google_review_id). Re-scrapes can recover a fuller
            # body after the crawler expands Google's "More" collapse — update when longer.
            existing: dict[str, Review] = {
                rid: row
                for rid, row in (
                    await s.execute(
                        select(Review.google_review_id, Review).where(Review.business_id == business_id)
                    )
                ).all()
            }
            new_count = 0
            updated_count = 0
            for r in result.reviews:
                prev = existing.get(r.google_review_id)
                if prev is not None:
                    new_text = (r.text or "").strip()
                    old_text = (prev.text or "").strip()
                    if new_text and len(new_text) > len(old_text):
                        prev.text = new_text
                        updated_count += 1
                    if r.review_time and prev.review_time is None:
                        prev.review_time = r.review_time
                    continue
                s.add(
                    Review(
                        business_id=business_id,
                        google_review_id=r.google_review_id,
                        author=r.author,
                        rating=r.rating,
                        text=r.text,
                        review_time=r.review_time,
                    )
                )
                new_count += 1

            s.add(
                RatingSnapshot(
                    business_id=business_id,
                    avg_rating=result.avg_rating,
                    review_count=result.review_count,
                )
            )
            # Refresh the place profile when the scrape found any of it.
            if result.address:
                business.address = result.address
            if result.phone:
                business.phone = result.phone
            if result.website:
                business.website = result.website
            if result.category:
                business.category = result.category
            if result.opening_hours:
                business.opening_hours = result.opening_hours
            alerts = await evaluate_alerts(s, business, prev_snapshot, result.avg_rating, result.review_count)

            business.status = BusinessStatus.IDLE.value
            business.consecutive_blocks = 0
            business.next_due_at = self._next_due(business.kind)
            await s.commit()
            log.info(
                "business %d scraped: avg=%.2f count=%d new_reviews=%d updated_texts=%d "
                "alerts=%d next_due=%s",
                business_id,
                result.avg_rating,
                result.review_count,
                new_count,
                updated_count,
                len(alerts),
                business.next_due_at,
            )

    async def _on_blocked(self, business_id: int, page_url: str) -> None:
        async with session_factory() as s:
            business = await s.get(Business, business_id)
            if business is None:
                return
            s.add(BlockEvent(business_id=business_id, page_url=page_url))
            business.consecutive_blocks += 1
            now = utcnow()
            if business.consecutive_blocks >= self.settings.max_consecutive_blocks:
                business.status = BusinessStatus.PARKED.value
                until = now + dt.timedelta(minutes=self.settings.park_minutes)
                business.parked_until = until
                business.next_due_at = until
                log.warning(
                    "business %d parked for %d min after %d consecutive blocks",
                    business_id,
                    self.settings.park_minutes,
                    business.consecutive_blocks,
                )
            else:
                backoff = self.settings.block_backoff_minutes
                minutes = backoff[min(business.consecutive_blocks - 1, len(backoff) - 1)]
                business.status = BusinessStatus.BACKOFF.value
                business.next_due_at = now + dt.timedelta(minutes=minutes)
                log.info(
                    "business %d backing off %d min (blocks=%d)",
                    business_id,
                    minutes,
                    business.consecutive_blocks,
                )
            await s.commit()

    async def _on_failure(self, business_id: int) -> None:
        async with session_factory() as s:
            business = await s.get(Business, business_id)
            if business is None:
                return
            minutes = self.settings.block_backoff_minutes[0]
            business.status = BusinessStatus.BACKOFF.value
            business.next_due_at = utcnow() + dt.timedelta(minutes=minutes)
            await s.commit()

    async def _reset_to_queued(self, business_id: int) -> None:
        async with session_factory() as s:
            await s.execute(
                update(Business)
                .where(Business.id == business_id, Business.status == BusinessStatus.SCRAPING.value)
                .values(status=BusinessStatus.QUEUED.value, next_due_at=utcnow())
            )
            await s.commit()

    def _next_due(self, kind: str) -> dt.datetime:
        if kind == "competitor":
            minutes = self.settings.default_interval_min_competitor
        else:
            minutes = self.settings.default_interval_min_own
        jitter = 1.0 + random.uniform(-self.settings.schedule_jitter_pct, self.settings.schedule_jitter_pct)
        return utcnow() + dt.timedelta(minutes=minutes * jitter)
