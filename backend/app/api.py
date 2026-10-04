"""HTTP API: businesses, reviews, snapshots, alerts, performance, stats, backup."""
from __future__ import annotations

import contextlib
import datetime as dt
import os
import tempfile
from typing import Any, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from . import backup as backup_lib
from .config import get_settings
from .db import dispose_engine, get_session, init_db
from .db.models import Alert, Business, BusinessStatus, PerformanceRow, RatingSnapshot, Review
from .gbp_csv import (
    METRIC_KEYS,
    ParsedPerformanceRow,
    parse_performance_csv,
    period_from_filename,
)
from .scheduler import utcnow
from .schemas import (
    AlertOut,
    BusinessCreate,
    BusinessOut,
    BusinessUpdate,
    PerformanceOut,
    PerformanceUploadOut,
    ReviewOut,
    SeenAllOut,
    SnapshotOut,
    StatsOut,
)

router = APIRouter(prefix="/api")

# Review endpoints back a list view that renders every row client-side: cap the payload so a
# growing table can never turn a 5-second poll into a megabyte of JSON.
REVIEW_LIMIT_DEFAULT = 300
REVIEW_LIMIT_MAX = 2000


def _next_due(kind: str) -> dt.datetime:
    s = get_settings()
    minutes = s.default_interval_min_competitor if kind == "competitor" else s.default_interval_min_own
    return utcnow() + dt.timedelta(minutes=minutes)


async def _latest_ratings(
    db: AsyncSession, business_ids: list[int]
) -> dict[int, tuple[float, int, dt.datetime]]:
    """Latest snapshot per business id (highest snapshot id wins).

    One aggregate + one join instead of loading every snapshot the business ever had —
    this endpoint backs the dashboard's 5-second polling. Carries `taken_at` too: a
    snapshot is written once per successful scrape, so it is the last-scrape time
    without needing its own column on `businesses`.
    """
    if not business_ids:
        return {}
    latest = (
        select(
            RatingSnapshot.business_id.label("business_id"),
            func.max(RatingSnapshot.id).label("max_id"),
        )
        .where(RatingSnapshot.business_id.in_(business_ids))
        .group_by(RatingSnapshot.business_id)
        .subquery()
    )
    rows = await db.execute(
        select(
            RatingSnapshot.business_id,
            RatingSnapshot.avg_rating,
            RatingSnapshot.review_count,
            RatingSnapshot.taken_at,
        ).join(latest, RatingSnapshot.id == latest.c.max_id)
    )
    return {
        business_id: (avg_rating, review_count, taken_at)
        for business_id, avg_rating, review_count, taken_at in rows.all()
    }


def _business_out(
    business: Business, ratings: dict[int, tuple[float, int, dt.datetime]] | None = None
) -> BusinessOut:
    avg_rating, review_count, taken_at = (ratings or {}).get(business.id, (None, None, None))  # type: ignore[assignment]
    return BusinessOut(
        id=business.id,
        name=business.name,
        maps_url=business.maps_url,
        kind=business.kind,
        avg_rating=avg_rating,
        review_count=review_count,
        status=business.status,
        address=business.address,
        phone=business.phone,
        website=business.website,
        category=business.category,
        opening_hours=business.opening_hours,
        next_due_at=business.next_due_at,
        last_scraped_at=taken_at,
        consecutive_blocks=business.consecutive_blocks,
        parked_until=business.parked_until,
        created_at=business.created_at,
        updated_at=business.updated_at,
    )


def _review_out(review: Review, business_name: str) -> ReviewOut:
    return ReviewOut(
        id=review.id,
        business_id=review.business_id,
        business_name=business_name,
        google_review_id=review.google_review_id,
        author=review.author,
        rating=review.rating,
        text=review.text,
        review_time=review.review_time,
        first_seen_at=review.first_seen_at,
    )


@router.post("/businesses", response_model=BusinessOut, status_code=201)
async def create_business(payload: BusinessCreate, db: AsyncSession = Depends(get_session)) -> Business:
    exists = (
        await db.execute(select(Business.id).where(func.lower(Business.name) == payload.name.lower()))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="business name already exists")
    business = Business(
        name=payload.name,
        maps_url=str(payload.maps_url),
        kind=payload.kind,
        status=BusinessStatus.QUEUED.value if payload.enqueue else BusinessStatus.IDLE.value,
        next_due_at=utcnow() if payload.enqueue else _next_due(payload.kind),
    )
    db.add(business)
    await db.flush()
    # Auto-sync: performance CSVs uploaded earlier under this (not-yet-tracked) name attach now.
    pending = (
        await db.execute(
            select(PerformanceRow).where(
                PerformanceRow.business_id.is_(None),
                func.lower(func.trim(PerformanceRow.source_name)) == payload.name.strip().lower(),
            )
        )
    ).scalars()
    for row in pending:
        row.business_id = business.id
    await db.commit()
    await db.refresh(business)
    return business


@router.patch("/businesses/{business_id}", response_model=BusinessOut)
async def update_business(
    business_id: int, payload: BusinessUpdate, db: AsyncSession = Depends(get_session)
) -> BusinessOut:
    """Edit name and/or Maps link; pending performance rows uploaded under the new name attach now."""
    business = await db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    if payload.name is None and payload.maps_url is None:
        raise HTTPException(status_code=422, detail="nothing to update")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="business name cannot be blank")
        clash = (
            await db.execute(
                select(Business.id).where(
                    func.lower(func.trim(Business.name)) == name.lower(), Business.id != business_id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(status_code=409, detail="business name already exists")

        business.name = name
        # Same auto-sync as create: CSV rows waiting under this name attach on rename.
        pending = (
            await db.execute(
                select(PerformanceRow).where(
                    PerformanceRow.business_id.is_(None),
                    func.lower(func.trim(PerformanceRow.source_name)) == name.lower(),
                )
            )
        ).scalars()
        for row in pending:
            row.business_id = business.id

    if payload.maps_url is not None:
        # The scraper reads this column on every run, so the next cycle uses the new link.
        business.maps_url = str(payload.maps_url)

    await db.commit()
    await db.refresh(business)
    return _business_out(business, await _latest_ratings(db, [business_id]))


@router.get("/businesses", response_model=list[BusinessOut])
async def list_businesses(db: AsyncSession = Depends(get_session)) -> list[BusinessOut]:
    rows = await db.execute(select(Business).order_by(Business.id))
    businesses = list(rows.scalars())
    ratings = await _latest_ratings(db, [b.id for b in businesses])
    return [_business_out(b, ratings) for b in businesses]


@router.get("/businesses/{business_id}", response_model=BusinessOut)
async def get_business(business_id: int, db: AsyncSession = Depends(get_session)) -> BusinessOut:
    business = await db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    return _business_out(business, await _latest_ratings(db, [business_id]))


@router.delete("/businesses/{business_id}", status_code=204)
async def delete_business(business_id: int, db: AsyncSession = Depends(get_session)) -> None:
    business = await db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    for table in (Review, RatingSnapshot, Alert):
        await db.execute(delete(table).where(table.business_id == business_id))
    await db.delete(business)
    await db.commit()


@router.post("/businesses/{business_id}/enqueue", response_model=BusinessOut)
async def enqueue_business(business_id: int, db: AsyncSession = Depends(get_session)) -> BusinessOut:
    """Queue one business for scraping right now (the 'run this task' action)."""
    business = await db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    if business.status == BusinessStatus.PARKED.value:
        raise HTTPException(status_code=409, detail="business is parked after repeated blocks")
    business.status = BusinessStatus.QUEUED.value
    business.next_due_at = utcnow()
    await db.commit()
    return _business_out(business, await _latest_ratings(db, [business_id]))


@router.post("/enqueue-all", response_model=list[BusinessOut])
async def enqueue_all(db: AsyncSession = Depends(get_session)) -> list[BusinessOut]:
    """Run all pending tasks: queue every business that isn't parked or already scraping."""
    rows = (
        await db.execute(
            select(Business).where(
                Business.status.notin_([BusinessStatus.PARKED.value, BusinessStatus.SCRAPING.value])
            )
        )
    ).scalars()
    businesses = list(rows)
    for b in businesses:
        b.status = BusinessStatus.QUEUED.value
        b.next_due_at = utcnow()
    await db.commit()
    # Same payload shape as GET /api/businesses (ratings included), so the UI never has to special-case it.
    ratings = await _latest_ratings(db, [b.id for b in businesses])
    return [_business_out(b, ratings) for b in businesses]


@router.get("/reviews", response_model=list[ReviewOut])
async def list_all_reviews(
    limit: int = Query(default=REVIEW_LIMIT_DEFAULT, ge=1, le=REVIEW_LIMIT_MAX),
    business_id: int | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[ReviewOut]:
    """Stored reviews, newest first — powers the dashboard's 'All' view (optional one-business filter)."""
    name_rows = await db.execute(select(Business.id, Business.name))
    names: dict[int, str] = {bid: name for bid, name in name_rows.all()}
    stmt = select(Review)
    if business_id is not None:
        stmt = stmt.where(Review.business_id == business_id)
    stmt = stmt.order_by(
        func.coalesce(Review.review_time, Review.first_seen_at).desc(), Review.id.desc()
    ).limit(limit)
    rows = await db.execute(stmt)
    return [_review_out(r, names.get(r.business_id, "")) for r in rows.scalars()]


@router.get("/businesses/{business_id}/reviews", response_model=list[ReviewOut])
async def list_reviews(
    business_id: int,
    limit: int = Query(default=REVIEW_LIMIT_DEFAULT, ge=1, le=REVIEW_LIMIT_MAX),
    db: AsyncSession = Depends(get_session),
) -> list[ReviewOut]:
    business = await db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    rows = await db.execute(
        select(Review)
        .where(Review.business_id == business_id)
        .order_by(func.coalesce(Review.review_time, Review.first_seen_at).desc(), Review.id.desc())
        .limit(limit)
    )
    return [_review_out(r, business.name) for r in rows.scalars()]


@router.get("/businesses/{business_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(business_id: int, db: AsyncSession = Depends(get_session)) -> list[RatingSnapshot]:
    if await db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="business not found")
    rows = await db.execute(
        select(RatingSnapshot)
        .where(RatingSnapshot.business_id == business_id)
        .order_by(RatingSnapshot.id.desc())
    )
    return list(rows.scalars())


@router.get("/businesses/{business_id}/performance", response_model=list[PerformanceOut])
async def list_performance(business_id: int, db: AsyncSession = Depends(get_session)) -> list[PerformanceRow]:
    """GBP performance rows for one business: newest report period first (date-less last)."""
    if await db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="business not found")
    rows = await db.execute(
        select(PerformanceRow)
        .where(PerformanceRow.business_id == business_id)
        .order_by(PerformanceRow.period_date.desc().nulls_last(), PerformanceRow.id.desc())
    )
    return list(rows.scalars())


@router.post("/performance/upload", response_model=PerformanceUploadOut, status_code=201)
async def upload_performance(
    file: UploadFile = File(...),
    business_id: int | None = Form(default=None),
    db: AsyncSession = Depends(get_session),
) -> PerformanceUploadOut:
    """Import a Google performance CSV; each row collides with a business via its location name."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        parsed = parse_performance_csv(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Account-level exports hold one row per location and no period column: those rows are keyed by
    # the date range Google puts in the file name ("… - 2026-8-1 - 2026-8-31 - <hash>.csv").
    file_period, file_period_date = period_from_filename(file.filename or "")
    source_name = parsed.business_name.strip() if parsed.business_name else ""

    groups: dict[str, list[ParsedPerformanceRow]] = {}
    for parsed_row in parsed.rows:
        groups.setdefault(parsed_row.location, []).append(parsed_row)
    named_locations = {loc for loc in groups if loc}
    if not named_locations and business_id is None:
        raise HTTPException(status_code=422, detail="CSV has no business name — pick a business explicitly")

    chosen: Business | None = None
    if business_id is not None:
        chosen = await db.get(Business, business_id)
        if chosen is None:
            raise HTTPException(status_code=404, detail="business not found")
    # The explicit pick also catches nameless CSVs and single-location files whose name matches nothing.
    single_location = len(named_locations) <= 1

    now = utcnow()
    attached: list[str] = []
    pending: list[str] = []
    matched: dict[int, Business] = {}
    period_keys: list[str] = []
    for location, group_rows in groups.items():
        business: Business | None = None
        if location:
            # Tabrak dengan business name field: row location must collide with businesses.name.
            business = (
                await db.execute(
                    select(Business).where(func.lower(func.trim(Business.name)) == location.lower())
                )
            ).scalars().first()
        if business is None and chosen is not None and (not location or single_location):
            business = chosen
        label = location or (business.name if business is not None else source_name)
        if business is None:
            # Replace previous pending rows for this location so re-uploading never duplicates.
            await db.execute(
                delete(PerformanceRow).where(
                    PerformanceRow.business_id.is_(None),
                    func.lower(func.trim(PerformanceRow.source_name)) == location.lower(),
                )
            )
            targets: dict[str, PerformanceRow] = {}
            pending.append(location)
        else:
            targets = {
                row.period: row
                for row in (
                    await db.execute(select(PerformanceRow).where(PerformanceRow.business_id == business.id))
                ).scalars()
            }
            matched[business.id] = business
            attached.append(label)

        for parsed_row in group_rows:
            # History key = the report period: a new period adds a record, the same one refreshes it.
            key = parsed_row.period or file_period or now.isoformat(timespec="seconds")
            target = targets.get(key)
            if target is None:
                target = PerformanceRow(
                    business_id=business.id if business is not None else None,
                    period=key,
                    source_name=label,
                )
                db.add(target)
                targets[key] = target
            target.period_date = parsed_row.period_date or file_period_date
            # "Uploaded" column / re-upload bookkeeping: the row keeps its period, refreshes its stamp.
            target.imported_at = now
            for metric in METRIC_KEYS:
                setattr(target, metric, getattr(parsed_row, metric))
            if key not in period_keys:
                period_keys.append(key)
    await db.commit()
    only = next(iter(matched.values())) if len(matched) == 1 else None
    return PerformanceUploadOut(
        business_id=only.id if only is not None else None,
        business_name=only.name if only is not None else source_name,
        matched=bool(matched),
        imported=len(parsed.rows),
        periods=period_keys,
        attached_locations=attached,
        pending_locations=pending,
    )


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    seen: bool | None = None,
    business_id: int | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.id.desc())
    if seen is not None:
        stmt = stmt.where(Alert.seen == seen)
    if business_id is not None:
        stmt = stmt.where(Alert.business_id == business_id)
    return list((await db.execute(stmt)).scalars())


@router.post("/alerts/seen-all", response_model=SeenAllOut)
async def mark_all_alerts_seen(db: AsyncSession = Depends(get_session)) -> SeenAllOut:
    """Clear the alert badge in one go (the per-alert button is too slow once the list grows)."""
    result = cast(
        "CursorResult[Any]",
        await db.execute(update(Alert).where(Alert.seen.is_(False)).values(seen=True)),
    )
    await db.commit()
    return SeenAllOut(updated=int(result.rowcount or 0))


@router.post("/alerts/{alert_id}/seen", response_model=AlertOut)
async def mark_alert_seen(alert_id: int, db: AsyncSession = Depends(get_session)) -> Alert:
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    alert.seen = True
    await db.commit()
    await db.refresh(alert)
    return alert


@router.get("/stats", response_model=StatsOut)
async def stats(db: AsyncSession = Depends(get_session)) -> StatsOut:
    status_rows = (await db.execute(select(Business.status, func.count()).group_by(Business.status))).all()
    by_status: dict[str, int] = {str(status): int(count) for status, count in status_rows}
    reviews = (await db.execute(select(func.count()).select_from(Review))).scalar_one()
    open_alerts = (
        await db.execute(select(func.count()).select_from(Alert).where(Alert.seen == False))  # noqa: E712
    ).scalar_one()
    return StatsOut(
        businesses=sum(by_status.values()),
        queued=by_status.get("queued", 0),
        scraping=by_status.get("scraping", 0),
        idle=by_status.get("idle", 0),
        backoff=by_status.get("backoff", 0),
        parked=by_status.get("parked", 0),
        reviews=reviews,
        open_alerts=open_alerts,
    )


# ---- Backup / restore (Kwerry /api/backup pattern) -------------------------
# Operates on the live SQLite file. Download checkpoints the WAL first so the
# copy is complete; restore swaps the upload over the live file (with a
# timestamped safety copy) and requires an engine recycle + restart, exactly
# like Kwerry's "restart the server to load the restored data".


@router.get("/backup")
async def download_backup() -> FileResponse:
    """Download a full SQLite backup (businesses, reviews, performance, alerts)."""
    db_path = backup_lib.database_path(get_settings().database_url)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%S")
    dest = os.path.join(tempfile.gettempdir(), f"peeker-backup-{stamp}.db")
    backup_lib.backup_database(db_path, dest)
    return FileResponse(
        dest,
        media_type="application/octet-stream",
        filename=f"peeker-backup-{stamp}.db",
    )


@router.post("/backup/restore")
async def restore_backup(file: UploadFile = File(...)) -> dict[str, str]:
    """Restore the database from an uploaded .db file. Restart the backend after."""
    db_path = backup_lib.database_path(get_settings().database_url)
    if not db_path:
        raise HTTPException(status_code=503, detail="Database backup/restore is SQLite-only.")
    raw = await file.read()
    if len(raw) < 100:
        raise HTTPException(status_code=400, detail="Backup file looks empty or invalid.")
    fd, tmp = tempfile.mkstemp(suffix=".db", prefix="restore-upload-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        if not backup_lib.is_sqlite_file(tmp):
            raise HTTPException(status_code=400, detail="File is not a valid SQLite database.")
        # The pool holds open handles on the live file: drop them before the
        # swap, then re-create tables/indexes on the fresh file afterwards.
        await dispose_engine()
        try:
            safety = backup_lib.restore_database(db_path, tmp)
        finally:
            await init_db()
        return {
            "ok": "true",
            "message": "Database restored. Restart the backend server to load the restored data.",
            "safety_copy": safety,
        }
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)
