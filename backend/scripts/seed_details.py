"""Seed one business with sample place details so the modal can be verified."""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import init_db, session_factory  # noqa: E402
from app.db.models import Business  # noqa: E402


async def main() -> None:
    await init_db()
    async with session_factory() as s:
        rows = (await s.execute(select(Business).order_by(Business.id))).scalars().all()
        print("businesses:", len(rows))
        cols_ok = all(
            hasattr(b, "address") for b in rows
        )
        print("detail columns present:", cols_ok)
        b = rows[0]
        b.address = "Jl. Setiabudi No. 45, Bandung, Jawa Barat 40141"
        b.phone = "(022) 2034-567"
        b.website = "https://www.bankexample.co.id"
        b.category = "Bank"
        b.opening_hours = (
            "Monday\t8:30 AM–3:00 PM\n"
            "Tuesday\t8:30 AM–3:00 PM\n"
            "Wednesday\t8:30 AM–3:00 PM\n"
            "Thursday\t8:30 AM–3:00 PM\n"
            "Friday\t8:30 AM–3:00 PM\n"
            "Saturday\tClosed\n"
            "Sunday\tClosed"
        )
        await s.commit()
        print("seeded", b.name)
        print("address", b.address)
        print("phone", b.phone)


if __name__ == "__main__":
    asyncio.run(main())
