"""Live scrape check: are full review comments captured after expanding More?

    .venv\\Scripts\\python.exe scripts\\live_scrape_check.py            # scrape + report only
    .venv\\Scripts\\python.exe scripts\\live_scrape_check.py --persist   # also store via the worker path
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.crawler.google_maps import GoogleMapsCrawler  # noqa: E402

# Surface the crawler's phase logs (pane opened / review-list switch / reloads) so a
# stalled or capped run is diagnosable from the output alone.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


async def main() -> None:
    conn = sqlite3.connect(pathlib.Path(__file__).resolve().parent.parent / "data" / "peeker.db")
    row = conn.execute(
        "select id, maps_url, name from businesses where name like '%Setiabudi%' limit 1"
    ).fetchone()
    if not row:
        row = conn.execute("select id, maps_url, name from businesses limit 1").fetchone()
    biz_id, url, name = row
    print("target:", name, url, flush=True)

    c = GoogleMapsCrawler()
    try:
        print("scraping...", flush=True)
        result = await c.scrape(url)
        print(
            "avg",
            result.avg_rating,
            "count",
            result.review_count,
            "n",
            len(result.reviews),
        )
        empty = sum(1 for r in result.reviews if not (r.text or "").strip())
        trunc = sum(1 for r in result.reviews if (r.text or "").rstrip().endswith("…"))
        print("empty", empty, "truncated_ellipsis", trunc)
        for r in result.reviews[:10]:
            t = (r.text or "").replace("\n", " ")[:100]
            print(f"  [{r.rating}] {r.author[:22]!r:24} len={len(r.text or ''):3} {t!r}")
    finally:
        await c.close()

    if "--persist" not in sys.argv:
        return
    # Persist through the production write path (WorkerPool._on_success): upsert reviews by
    # (business, google_review_id), add a snapshot, refresh the profile, evaluate alerts.
    from sqlalchemy import func, select

    from app.db import session_factory
    from app.db.models import Review
    from app.worker import WorkerPool

    before = conn.execute("select count(*) from reviews where business_id=?", (biz_id,)).fetchone()[0]
    pool = WorkerPool(GoogleMapsCrawler())
    try:
        await pool._on_success(biz_id, result)
    finally:
        await pool.crawler.close()
    async with session_factory() as s:
        after = await s.scalar(select(func.count()).select_from(Review).where(Review.business_id == biz_id))
    print(
        f"DB reviews for business {biz_id}: before={before} after={int(after)} "
        f"scraped={len(result.reviews)}",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
