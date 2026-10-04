"""Performance CSV upload: business-name collision, metric filtering, upsert, ordering."""
from __future__ import annotations

import datetime as dt

from app.gbp_csv import period_from_filename
from app.main import create_app
from tests.conftest import api_client

_HEADER = (
    "Period,Location Name,Google Search - Mobile,Google Search - Desktop,"
    "Google Maps - Mobile,Google Maps - Desktop,Calls,Directions,Website Clicks,Messages,Bookings\n"
)
CSV = (
    "Business name: WARUNG TEKKO\n"
    "Date range: Jan 1, 2026 - Jan 3, 2026\n"
    "\n"
    + _HEADER
    + "2026-01-01,Warung Tekko,10,5,3,2,1,4,7,99,11\n"
    + "2026-01-02,Warung Tekko,12,6,4,3,2,5,8,88,22\n"
    + '"Jan 3, 2026",Warung Tekko,14,7,5,4,3,6,9,77,33\n'
    + "Week 1,Warung Tekko,1,1,1,1,0,1,1,5,5\n"
)
NAMELESS = (
    "Period,Google Search - Mobile,Google Search - Desktop,Google Maps - Mobile,"
    "Google Maps - Desktop,Calls,Directions,Website Clicks\n"
    "2026-02-01,1,2,3,4,5,6,7\n"
)
_ACCOUNT_HEADER = (
    "Store code,Business name,Address,Labels,Google Search - Mobile,Google Search - Desktop,"
    "Google Maps - Mobile,Google Maps - Desktop,Calls,Bookings,Directions,Website clicks\n"
)
# Account-level export: one row per location, a metric-description row, and no period column at all.
_ACCOUNT_CSV = (
    _ACCOUNT_HEADER
    + ",,,,,Number of people that viewed,Number of people that viewed,,,,\n"
    + "UOBIDC-001,Bank UOB KC Gajah Mada,Jl. Gajah Mada 87,,709,260,1179,153,5,0,161,1\n"
    + "UOBIDC-118,UOB Setiabudi JKT,Jl. Setiabudi,,290,114,498,79,2,0,84,0\n"
    + "UOBIDC-588,Bank UOB KCP Cemara Asri,Jl. Cemara,,449,95,453,56,8,0,108,1\n"
)
_ACCOUNT_FILE = "GMB insights (Performance Report) - UOB Indonesia - 2026-8-1 - 2026-8-31 - a1b2.csv"
# Same location, two consecutive monthly exports + a corrected re-upload of the August one.
_AUG_FILE = "GMB insights - UOB Indonesia - 2026-8-1 - 2026-8-31 - a1b2.csv"
_SEP_FILE = "GMB insights - UOB Indonesia - 2026-9-1 - 2026-9-30 - c3d4.csv"
_AUG_ROW = "UOBIDC-001,Bank UOB KC Gajah Mada,Jl. Gajah Mada 87,,709,260,1179,153,5,0,161,1\n"
_SEP_ROW = "UOBIDC-001,Bank UOB KC Gajah Mada,Jl. Gajah Mada 87,,800,300,1300,170,6,0,200,2\n"
_AUG_ROW_FIXED = "UOBIDC-001,Bank UOB KC Gajah Mada,Jl. Gajah Mada 87,,711,261,1180,154,5,0,162,1\n"


async def test_performance_upload_matches_business_name() -> None:
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/businesses",
            json={
                "name": "Warung Tekko",
                "maps_url": "https://maps.google.com/?cid=9",
                "enqueue": False,
            },
        )
        bid = resp.json()["id"]

        # CSV business name (any case) collides with the business name field.
        resp = await client.post(
            "/api/performance/upload",
            files={"file": ("perf.csv", CSV.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 201, resp.text
        up = resp.json()
        assert up["business_id"] == bid
        assert up["business_name"] == "Warung Tekko"
        assert up["matched"] is True
        assert up["imported"] == 4
        assert up["periods"][0] == "2026-01-01"

        # Recent first; date-less period ("Week 1") last; extra columns (Messages/Bookings) dropped.
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert [r["period"] for r in rows] == ["Jan 3, 2026", "2026-01-02", "2026-01-01", "Week 1"]
        assert rows[0]["search_mobile"] == 14
        assert rows[0]["website_clicks"] == 9
        assert rows[0]["calls"] == 3
        assert rows[0]["period_date"] == "2026-01-03"
        assert rows[3]["period_date"] is None
        assert "messages" not in rows[0] and "bookings" not in rows[0]

        # Re-upload upserts: same periods update, never duplicate.
        resp = await client.post(
            "/api/performance/upload",
            files={"file": ("perf.csv", CSV.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 201
        assert resp.json()["imported"] == 4
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert len(rows) == 4

        # 404 for unknown business id on read.
        assert (await client.get("/api/businesses/9999/performance")).status_code == 404


async def test_performance_upload_error_paths() -> None:
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/businesses",
            json={
                "name": "Kopi Nusantara",
                "maps_url": "https://maps.google.com/?cid=10",
                "enqueue": False,
            },
        )
        bid = resp.json()["id"]

        # Explicit business id that does not exist → 404.
        resp = await client.post(
            "/api/performance/upload",
            data={"business_id": "9999"},
            files={"file": ("perf.csv", NAMELESS.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 404

        # No metric columns at all → 422.
        resp = await client.post(
            "/api/performance/upload",
            files={"file": ("bad.csv", b"foo,bar\n1,2\n", "text/csv")},
        )
        assert resp.status_code == 422

        # Nameless CSV: 422 without an explicit business, 201 with one.
        resp = await client.post(
            "/api/performance/upload",
            files={"file": ("perf.csv", NAMELESS.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 422
        resp = await client.post(
            "/api/performance/upload",
            data={"business_id": str(bid)},
            files={"file": ("perf.csv", NAMELESS.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["business_name"] == "Kopi Nusantara"
        assert resp.json()["matched"] is True
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert len(rows) == 1
        assert rows[0]["maps_desktop"] == 4
        assert rows[0]["directions"] == 6


async def test_performance_upload_pending_then_syncs_on_create() -> None:
    """A CSV naming an untracked location is stored pending and attaches when that business is created."""
    app = create_app()
    async with api_client(app) as client:
        ghost = "Business name: Ghost Bistro\n\n" + _HEADER + "2026-01-01,Ghost Bistro,1,2,3,4,5,6,7,0,0\n"
        resp = await client.post(
            "/api/performance/upload",
            files={"file": ("perf.csv", ghost.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 201, resp.text
        up = resp.json()
        assert up["matched"] is False
        assert up["business_id"] is None
        assert up["business_name"] == "Ghost Bistro"
        assert up["imported"] == 1
        assert up["periods"] == ["2026-01-01"]

        # Re-upload replaces the pending copy instead of duplicating rows.
        resp = await client.post(
            "/api/performance/upload",
            files={"file": ("perf.csv", ghost.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 201
        assert resp.json()["imported"] == 1

        # Adding the location syncs the stored rows (name compare is case-insensitive).
        resp = await client.post(
            "/api/businesses",
            json={
                "name": "GHOST bistro",
                "maps_url": "https://maps.google.com/?cid=11",
                "enqueue": False,
            },
        )
        assert resp.status_code == 201, resp.text
        bid = resp.json()["id"]
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert len(rows) == 1
        assert rows[0]["search_mobile"] == 1
        assert rows[0]["maps_desktop"] == 4
        assert rows[0]["website_clicks"] == 7


def test_period_from_filename_reads_the_export_range() -> None:
    assert period_from_filename(_ACCOUNT_FILE) == ("2026-08-01 – 2026-08-31", dt.date(2026, 8, 31))
    assert period_from_filename("perf.csv") == ("", None)


async def test_performance_account_level_csv_splits_per_location() -> None:
    """One row per location, no period column: rows are keyed by the range in the file name."""
    app = create_app()
    async with api_client(app) as client:
        ids: dict[str, int] = {}
        for cid, name in ((21, "Bank UOB KC Gajah Mada"), (22, "UOB Setiabudi JKT")):
            resp = await client.post(
                "/api/businesses",
                json={"name": name, "maps_url": f"https://maps.google.com/?cid={cid}", "enqueue": False},
            )
            assert resp.status_code == 201, resp.text
            ids[name] = resp.json()["id"]

        resp = await client.post(
            "/api/performance/upload",
            files={"file": (_ACCOUNT_FILE, _ACCOUNT_CSV.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 201, resp.text
        up = resp.json()
        assert up["imported"] == 3  # the metric-description row is dropped
        assert up["matched"] is True
        assert up["business_id"] is None  # two locations landed on two different businesses
        assert up["attached_locations"] == ["Bank UOB KC Gajah Mada", "UOB Setiabudi JKT"]
        assert up["pending_locations"] == ["Bank UOB KCP Cemara Asri"]
        assert up["periods"] == ["2026-08-01 – 2026-08-31"]

        # Each location keeps its own metrics, keyed by the export's date range.
        rows = (await client.get(f"/api/businesses/{ids['Bank UOB KC Gajah Mada']}/performance")).json()
        assert len(rows) == 1
        assert rows[0]["source_name"] == "Bank UOB KC Gajah Mada"
        assert rows[0]["search_mobile"] == 709 and rows[0]["maps_mobile"] == 1179
        assert rows[0]["period_date"] == "2026-08-31"
        rows = (await client.get(f"/api/businesses/{ids['UOB Setiabudi JKT']}/performance")).json()
        assert len(rows) == 1
        assert rows[0]["search_desktop"] == 114 and rows[0]["website_clicks"] == 0

        # Re-uploading the same file refreshes in place — it never duplicates rows.
        resp = await client.post(
            "/api/performance/upload",
            files={"file": (_ACCOUNT_FILE, _ACCOUNT_CSV.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 201
        rows = (await client.get(f"/api/businesses/{ids['Bank UOB KC Gajah Mada']}/performance")).json()
        assert len(rows) == 1

        # The untracked location waited as one pending copy; adding it attaches exactly that row.
        resp = await client.post(
            "/api/businesses",
            json={
                "name": "Bank UOB KCP Cemara Asri",
                "maps_url": "https://maps.google.com/?cid=23",
                "enqueue": False,
            },
        )
        assert resp.status_code == 201, resp.text
        rows = (await client.get(f"/api/businesses/{resp.json()['id']}/performance")).json()
        assert len(rows) == 1
        assert rows[0]["search_mobile"] == 449 and rows[0]["directions"] == 108
        assert rows[0]["source_name"] == "Bank UOB KCP Cemara Asri"


async def test_performance_uploads_keep_each_report_period_as_history() -> None:
    """Every uploaded report period is kept as its own record; re-uploading one only refreshes it."""
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/businesses",
            json={
                "name": "Bank UOB KC Gajah Mada",
                "maps_url": "https://maps.google.com/?cid=31",
                "enqueue": False,
            },
        )
        assert resp.status_code == 201, resp.text
        bid = resp.json()["id"]

        async def upload(filename: str, row: str) -> dict:
            resp = await client.post(
                "/api/performance/upload",
                files={"file": (filename, (_ACCOUNT_HEADER + row).encode("utf-8"), "text/csv")},
            )
            assert resp.status_code == 201, resp.text
            return resp.json()

        await upload(_AUG_FILE, _AUG_ROW)
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert [r["period"] for r in rows] == ["2026-08-01 – 2026-08-31"]
        assert rows[0]["period_date"] == "2026-08-31"
        assert rows[0]["search_mobile"] == 709

        # Next month's report lands as a new record and August stays as history.
        await upload(_SEP_FILE, _SEP_ROW)
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert [r["period"] for r in rows] == ["2026-09-01 – 2026-09-30", "2026-08-01 – 2026-08-31"]
        assert [r["period_date"] for r in rows] == ["2026-09-30", "2026-08-31"]
        assert rows[0]["search_mobile"] == 800 and rows[0]["calls"] == 6
        assert rows[1]["search_mobile"] == 709 and rows[1]["calls"] == 5  # untouched

        # Re-uploading a period refreshes that record instead of duplicating it.
        await upload(_AUG_FILE, _AUG_ROW_FIXED)
        rows = (await client.get(f"/api/businesses/{bid}/performance")).json()
        assert len(rows) == 2
        august = next(r for r in rows if r["period"] == "2026-08-01 – 2026-08-31")
        assert august["search_mobile"] == 711 and august["directions"] == 162
        assert august["imported_at"] > rows[0]["imported_at"]  # stamp refreshed, period kept
