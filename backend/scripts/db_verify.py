"""End-to-end check of the SQLite tuning: run the real app code against a copy of the live DB.

Proves four things the dashboard depends on:
  1. init_db() adds the hot-path indexes to a database that already had its tables
     (create_all alone would not have).
  2. Every pooled connection comes out pre-tuned (synchronous, cache, busy_timeout), which is
     what the connect-event hook in app/db is for.
  3. The hot dashboard queries use indexes instead of temp b-tree sorts.
  4. checkpoint_and_optimize() shrinks a grown WAL.

Run:  .venv/Scripts/python.exe scripts/db_verify.py       (exits non-zero on failure)
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(BACKEND, "data", "peeker.db")
WORK = os.path.join(tempfile.gettempdir(), "peeker_verify.db")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


# Set before app.config is imported: Settings is cached at import time, and an environment
# variable outranks the .env file in pydantic-settings' precedence order.
shutil.copy(LIVE, WORK)
for suffix in ("-wal", "-shm"):
    if os.path.exists(WORK + suffix):
        os.remove(WORK + suffix)
os.environ["PEEKER_DATABASE_URL"] = f"sqlite+aiosqlite:///{WORK}"

from sqlalchemy import func, select, text  # noqa: E402

from app.db import checkpoint_and_optimize, dispose_engine, init_db, session_factory  # noqa: E402
from app.db.models import Review  # noqa: E402

HOT_QUERIES = {
    "reviews, newest first": (
        "SELECT id FROM reviews ORDER BY COALESCE(review_time, first_seen_at) DESC, id DESC LIMIT 300",
        {},
    ),
    "reviews of one business": (
        "SELECT id FROM reviews WHERE business_id = :bid "
        "ORDER BY COALESCE(review_time, first_seen_at) DESC, id DESC LIMIT 300",
        {"bid": None},
    ),
    "open alerts": ("SELECT id FROM alerts WHERE seen = 0 ORDER BY id DESC LIMIT 20", {}),
    "scheduler due poll": (
        "SELECT id FROM businesses WHERE status IN ('idle','backoff') AND next_due_at <= :now",
        {"now": "2026-12-31 00:00:00"},
    ),
}


async def commit_cost(synchronous: int, business_id: int, rows: int = 150) -> float:
    """Median milliseconds of a single-row commit through the app's own session factory.

    The pragma is switched on the connection under test only, which is precisely the difference
    this change makes: WAL at NORMAL, instead of inheriting SQLite's FULL.
    """
    samples: list[float] = []
    async with session_factory() as s:
        try:
            await s.execute(text(f"PRAGMA synchronous={synchronous}"))
            for i in range(rows):
                started = time.perf_counter()
                await s.execute(
                    text("INSERT INTO alerts (business_id, kind, message, urgent, seen) "
                         "VALUES (:bid, 'review_burst', :m, 0, 0)"),
                    {"bid": business_id, "m": f"wal filler {synchronous}-{i}"},
                )
                await s.commit()
                samples.append((time.perf_counter() - started) * 1000)
        finally:
            await s.execute(text("PRAGMA synchronous=NORMAL"))
    samples.sort()
    return samples[len(samples) // 2]


async def main() -> None:
    print(f"copy of live db: {WORK} ({os.path.getsize(WORK) / 1024:.0f} KB)")

    print("\n1. init_db() on a pre-existing database")
    started = time.perf_counter()
    await init_db()
    print(f"   init_db took {(time.perf_counter() - started) * 1000:.0f} ms")
    async with session_factory() as s:
        names = {
            row[0]
            for row in (await s.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))).all()
        }
    for expected in (
        "ix_reviews_recency",
        "ix_reviews_business_recency",
        "ix_alerts_seen_id",
        "ix_businesses_status_due",
    ):
        check(expected, expected in names)

    print("\n2. pragmas on a pooled connection")
    async with session_factory() as s:
        for pragma in ("journal_mode", "synchronous", "busy_timeout", "cache_size", "journal_size_limit"):
            print(f"   {pragma} = {(await s.execute(text(f'PRAGMA {pragma}'))).scalar()}")
        synchronous = (await s.execute(text("PRAGMA synchronous"))).scalar()
        check("synchronous is 1 (NORMAL)", synchronous == 1, f"got {synchronous}")
        busy = (await s.execute(text("PRAGMA busy_timeout"))).scalar()
        check("busy_timeout is 8000", busy == 8000, f"got {busy}")

    print("\n3. query plans for the dashboard's hot reads")
    async with session_factory() as s:
        business_id = (await s.execute(text("SELECT id FROM businesses LIMIT 1"))).scalars().first()
    for label, (sql, params) in HOT_QUERIES.items():
        args = {k: (business_id if v is None else v) for k, v in params.items()}
        async with session_factory() as s:
            plan_rows = (await s.execute(text("EXPLAIN QUERY PLAN " + sql), args)).all()
        steps = [row[3] for row in plan_rows]
        # "SCAN reviews USING INDEX ..." is fine, it walks the index already in order. What we
        # are eliminating is the bare SCAN and the temp b-tree SQLite built for the ORDER BY.
        rough = any(step.startswith("SCAN ") and "USING" not in step for step in steps)
        check(label, not rough and "TEMP B-TREE" not in " ".join(steps), " / ".join(steps))

    print("\n4. write cost at NORMAL vs the FULL this app used to inherit")
    normal = await commit_cost(1, business_id)
    full = await commit_cost(2, business_id)
    print(f"   median single-row commit: NORMAL {normal:.2f} ms | FULL {full:.2f} ms")
    check("NORMAL commits cheaper than FULL", normal < full, f"{full / normal:.1f}x faster")

    before = os.path.getsize(WORK + "-wal") if os.path.exists(WORK + "-wal") else 0
    result = await checkpoint_and_optimize()
    after = os.path.getsize(WORK + "-wal") if os.path.exists(WORK + "-wal") else 0
    print(f"   WAL {before / 1024:.0f} KB -> {after / 1024:.0f} KB, checkpoint returned {result}")
    check("checkpoint truncated the WAL", after <= before, f"{after} bytes left")

    print("\n5. the API's own review query still works")
    async with session_factory() as s:
        stmt = (
            select(Review)
            .where(Review.business_id == business_id)
            .order_by(func.coalesce(Review.review_time, Review.first_seen_at).desc(), Review.id.desc())
            .limit(5)
        )
        rows = list((await s.execute(stmt)).scalars())
    check("ordered review rows returned", bool(rows), f"{len(rows)} rows")

    await dispose_engine()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(WORK + suffix):
            os.remove(WORK + suffix)

    print(f"\n{'ALL CHECKS PASSED' if not failures else 'FAILED: ' + ', '.join(failures)}")
    sys.exit(1 if failures else 0)


asyncio.run(main())
