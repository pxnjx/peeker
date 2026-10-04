"""Create the database and seed sample QUEUED businesses.

Usage: python scripts/seed.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow `python scripts/seed.py`

from sqlalchemy import select  # noqa: E402

from app.db import init_db, session_factory  # noqa: E402
from app.db.models import Business, BusinessStatus  # noqa: E402

SAMPLE_BUSINESSES = [
    # Replace maps_url values with real Google Maps place links of your choice.
    ("Demo Cafe (own)", "https://maps.google.com/?cid=12733406313454648823", "own"),
    ("Rival Pizza (competitor)", "https://maps.google.com/?cid=15275801448486108470", "competitor"),
]


async def main() -> None:
    await init_db()
    created = 0
    now = dt.datetime.now(dt.UTC)
    async with session_factory() as s:
        existing = {name for (name,) in await s.execute(select(Business.name))}
        for name, url, kind in SAMPLE_BUSINESSES:
            if name in existing:
                continue
            s.add(
                Business(
                    name=name,
                    maps_url=url,
                    kind=kind,
                    status=BusinessStatus.QUEUED.value,
                    next_due_at=now,
                )
            )
            created += 1
        await s.commit()
        count = (await s.execute(select(Business))).scalars().all()
    print(f"seeded {created} new businesses; total in DB: {len(count)}")
    for b in count:
        print(f"  #{b.id} {b.name} [{b.kind}] status={b.status}")


if __name__ == "__main__":
    asyncio.run(main())
