"""API tests: business CRUD, enqueue-all ('run all pending tasks'), alerts, stats."""
from __future__ import annotations

import datetime as dt

from app.db import session_factory
from app.db.models import Alert, Business, BusinessStatus, RatingSnapshot, Review
from app.main import create_app
from app.scheduler import utcnow
from tests.conftest import api_client


async def test_health() -> None:
    app = create_app()
    async with api_client(app) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_business_crud_and_enqueue_all() -> None:
    app = create_app()
    async with api_client(app) as client:
        # create
        resp = await client.post(
            "/api/businesses",
            json={"name": "Beta Bakery", "maps_url": "https://maps.google.com/?cid=42", "kind": "own"},
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["status"] == "queued"  # enqueue=True by default

        # duplicate name → 409
        resp = await client.post(
            "/api/businesses",
            json={"name": "beta bakery", "maps_url": "https://maps.google.com/?cid=43"},
        )
        assert resp.status_code == 409

        # make it idle+due so there is something "pending"
        async with session_factory() as s:
            row = await s.get(Business, created["id"])
            assert row is not None
            row.status = BusinessStatus.IDLE.value
            row.next_due_at = utcnow() - dt.timedelta(minutes=5)
            await s.commit()

        # list
        resp = await client.get("/api/businesses")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # run all pending tasks → the idle one becomes queued again
        resp = await client.post("/api/enqueue-all")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["status"] == "queued"
        assert items[0]["next_due_at"] is not None
        # Same shape as GET /api/businesses — re-queueing must not blank the table's rating
        # columns out (a raw ORM row used to serialise without the latest snapshot).
        assert "avg_rating" in items[0]
        assert "review_count" in items[0]

        # stats
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["businesses"] == 1
        assert stats["queued"] == 1

        # 404s
        assert (await client.get("/api/businesses/999")).status_code == 404
        assert (await client.post("/api/businesses/999/enqueue")).status_code == 404

        # delete
        resp = await client.delete(f"/api/businesses/{created['id']}")
        assert resp.status_code == 204
        assert (await client.get("/api/businesses")).json() == []


async def test_alerts_endpoints() -> None:
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/businesses",
            json={"name": "Gamma Gym", "maps_url": "https://maps.google.com/?cid=7", "kind": "competitor"},
        )
        bid = resp.json()["id"]
        async with session_factory() as s:
            s.add(
                Alert(
                    business_id=bid,
                    kind="rating_drop",
                    message="dropped",
                    urgent=False,
                )
            )
            await s.commit()

        resp = await client.get("/api/alerts", params={"seen": False})
        assert resp.status_code == 200
        alerts = resp.json()
        assert len(alerts) == 1
        alert_id = alerts[0]["id"]

        resp = await client.post(f"/api/alerts/{alert_id}/seen")
        assert resp.status_code == 200
        assert resp.json()["seen"] is True

        resp = await client.get("/api/alerts", params={"seen": False})
        assert resp.json() == []


async def test_alerts_seen_all_clears_every_unseen_alert() -> None:
    """One click for the whole badge — clearing alerts one by one is unusable once they pile up."""
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/businesses",
            json={"name": "Zeta Yoga", "maps_url": "https://maps.google.com/?cid=77", "enqueue": False},
        )
        bid = resp.json()["id"]
        async with session_factory() as s:
            s.add_all(
                [
                    Alert(business_id=bid, kind="rating_drop", message="dropped", urgent=True),
                    Alert(business_id=bid, kind="new_reviews", message="3 new reviews", urgent=False),
                ]
            )
            await s.commit()

        resp = await client.post("/api/alerts/seen-all")
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2

        assert (await client.get("/api/alerts", params={"seen": False})).json() == []
        assert len((await client.get("/api/alerts")).json()) == 2  # history is kept, only flagged

        # Second call is a no-op, not an error.
        assert (await client.post("/api/alerts/seen-all")).json()["updated"] == 0


async def test_business_rating_and_all_reviews_sorted() -> None:
    app = create_app()
    async with api_client(app) as client:
        r1 = await client.post(
            "/api/businesses",
            json={"name": "Delta Depot", "maps_url": "https://maps.google.com/?cid=11", "enqueue": False},
        )
        r2 = await client.post(
            "/api/businesses",
            json={"name": "Echo Eatery", "maps_url": "https://maps.google.com/?cid=12", "enqueue": False},
        )
        b1, b2 = r1.json()["id"], r2.json()["id"]

        async with session_factory() as s:
            s.add(RatingSnapshot(business_id=b1, avg_rating=4.2, review_count=7, taken_at=utcnow()))
            s.add(
                Review(
                    business_id=b1,
                    google_review_id="old",
                    author="A",
                    rating=4.0,
                    text="old",
                    review_time=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                    first_seen_at=utcnow(),
                )
            )
            s.add(
                Review(
                    business_id=b1,
                    google_review_id="new",
                    author="B",
                    rating=5.0,
                    text="new",
                    review_time=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
                    first_seen_at=utcnow(),
                )
            )
            s.add(
                Review(
                    business_id=b2,
                    google_review_id="fresh",
                    author="C",
                    rating=3.0,
                    text="fresh",
                    review_time=None,
                    first_seen_at=utcnow(),
                )
            )
            await s.commit()

        # Businesses list carries the latest snapshot rating.
        by_id = {item["id"]: item for item in (await client.get("/api/businesses")).json()}
        assert by_id[b1]["avg_rating"] == 4.2
        assert by_id[b1]["review_count"] == 7
        assert by_id[b2]["avg_rating"] is None  # never scraped → no snapshot

        # All-reviews endpoint: newest first (coalesce(review_time, first_seen_at) desc).
        items = (await client.get("/api/reviews")).json()
        assert [i["text"] for i in items] == ["fresh", "new", "old"]
        assert [i["business_name"] for i in items] == ["Echo Eatery", "Delta Depot", "Delta Depot"]
        assert items[0]["business_id"] == b2

        # Per-business endpoint also carries the name and the same ordering.
        per_biz = (await client.get(f"/api/businesses/{b1}/reviews")).json()
        assert [i["text"] for i in per_biz] == ["new", "old"]
        assert all(i["business_name"] == "Delta Depot" for i in per_biz)

        # The polling views render one page at a time, so the payload must be capped — an
        # unbounded list is what made every 5s poll slower than the one before it.
        capped = (await client.get("/api/reviews", params={"limit": 1})).json()
        assert [i["text"] for i in capped] == ["fresh"]
        scoped = (await client.get("/api/reviews", params={"business_id": b1})).json()
        assert [i["text"] for i in scoped] == ["new", "old"]
        assert [i["business_name"] for i in scoped] == ["Delta Depot", "Delta Depot"]
        capped_one = (await client.get(f"/api/businesses/{b1}/reviews", params={"limit": 1})).json()
        assert [i["text"] for i in capped_one] == ["new"]


# Account-level export row (no period column) used by the rename test below.
_CSV_ROW = (
    "Store code,Business name,Google Search - Mobile,Google Search - Desktop,Calls\n"
    "UOBIDC-999,Bank UOB KC Pacific Century Place,321,45,6\n"
)


async def test_business_rename_attaches_pending_performance() -> None:
    """Renaming fixes a typo and pulls in the pending CSV row stored under Google's spelling."""
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/businesses",
            json={
                "name": "Bank UOB KCU Pacific Century Place",
                "maps_url": "https://maps.google.com/?cid=51",
                "enqueue": False,
            },
        )
        assert resp.status_code == 201, resp.text
        bid = resp.json()["id"]

        # The CSV row carries Google's spelling → no collision yet, so it waits as pending.
        resp = await client.post(
            "/api/performance/upload",
            files={
                "file": (
                    "GMB insights - 2026-8-1 - 2026-8-31 - a1b2.csv",
                    _CSV_ROW.encode("utf-8"),
                    "text/csv",
                )
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["pending_locations"] == ["Bank UOB KC Pacific Century Place"]
        assert (await client.get(f"/api/businesses/{bid}/performance")).json() == []

        resp = await client.patch(
            f"/api/businesses/{bid}", json={"name": "Bank UOB KC Pacific Century Place"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Bank UOB KC Pacific Century Place"
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert len(rows) == 1
        assert rows[0]["search_mobile"] == 321 and rows[0]["calls"] == 6

        # Blank name → 422, another business' name → 409, unknown id → 404.
        assert (await client.patch(f"/api/businesses/{bid}", json={"name": "   "})).status_code == 422
        resp = await client.post(
            "/api/businesses",
            json={"name": "Taken Cafe", "maps_url": "https://maps.google.com/?cid=52", "enqueue": False},
        )
        assert resp.status_code == 201
        assert (await client.patch(f"/api/businesses/{bid}", json={"name": "taken cafe"})).status_code == 409
        assert (await client.patch("/api/businesses/9999", json={"name": "Nope"})).status_code == 404
        names = [b["name"] for b in (await client.get("/api/businesses")).json()]
        assert "Bank UOB KC Pacific Century Place" in names  # rejected attempts changed nothing


async def test_business_update_name_and_maps_url() -> None:
    """The edit dialog patches both columns: the name (CSV attach key) and the scraper's link."""
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/businesses",
            json={
                "name": "Edit Diner",
                "maps_url": "https://maps.google.com/?cid=70",
                "enqueue": False,
            },
        )
        assert resp.status_code == 201, resp.text
        bid = resp.json()["id"]

        # Maps link only → the name stays as it was.
        resp = await client.patch(
            f"/api/businesses/{bid}", json={"maps_url": "https://maps.google.com/?cid=71"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["maps_url"].endswith("cid=71")
        assert resp.json()["name"] == "Edit Diner"

        # Both fields at once — exactly what the edit dialog sends.
        resp = await client.patch(
            f"/api/businesses/{bid}",
            json={"name": "Edit Diner Bistro", "maps_url": "https://maps.google.com/?cid=72"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Edit Diner Bistro"
        assert resp.json()["maps_url"].endswith("cid=72")

        # Empty patch → 422, malformed URL → 422, unknown id → 404.
        assert (await client.patch(f"/api/businesses/{bid}", json={})).status_code == 422
        assert (await client.patch(f"/api/businesses/{bid}", json={"maps_url": "nope"})).status_code == 422
        assert (
            await client.patch(
                "/api/businesses/9999", json={"maps_url": "https://maps.google.com/?cid=73"}
            )
        ).status_code == 404

