"""Alert evaluation: rating drops and review bursts, with dedupe window."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db.base import utcnow
from .db.models import Alert, AlertKind, Business, RatingSnapshot, Review


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


async def _has_recent_dup(session: AsyncSession, business_id: int, kind: AlertKind) -> bool:
    settings = get_settings()
    cutoff = utcnow() - dt.timedelta(hours=settings.alert_dedupe_window_h)
    q = await session.execute(
        select(Alert.id).where(
            Alert.business_id == business_id,
            Alert.kind == kind.value,
            Alert.created_at >= cutoff,
        )
    )
    return q.scalar_one_or_none() is not None


async def evaluate_alerts(
    session: AsyncSession,
    business: Business,
    prev_snapshot: RatingSnapshot | None,
    new_avg: float,
    new_count: int,
) -> list[Alert]:
    """Create alerts for one completed scrape. `prev_snapshot` is the snapshot taken *before* this scrape."""
    settings = get_settings()
    now = utcnow()
    created: list[Alert] = []

    if prev_snapshot is not None:
        prev_avg = prev_snapshot.avg_rating
        prev_at = _aware(prev_snapshot.taken_at)
        drop = prev_avg - new_avg
        age_h = (now - prev_at).total_seconds() / 3600 if prev_at else None
        if age_h is not None:
            # Rating drops are one alert "family": never fire normal when an urgent
            # one already exists in the window, and dedupe each kind against itself.
            urgent_w = settings.alert_rating_drop_urgent_window_h
            if drop >= settings.alert_rating_drop_urgent_delta and age_h <= urgent_w:
                if not await _has_recent_dup(session, business.id, AlertKind.RATING_DROP_URGENT):
                    created.append(
                        Alert(
                            business_id=business.id,
                            kind=AlertKind.RATING_DROP_URGENT.value,
                            message=(
                                f"{business.name}: rating dropped {drop:.2f} "
                                f"({prev_avg:.2f} → {new_avg:.2f}) within {urgent_w}h"
                            ),
                            urgent=True,
                        )
                    )
            elif (
                drop >= settings.alert_rating_drop_delta
                and age_h <= settings.alert_rating_drop_window_h
                and not await _has_recent_dup(session, business.id, AlertKind.RATING_DROP)
                and not await _has_recent_dup(session, business.id, AlertKind.RATING_DROP_URGENT)
            ):
                created.append(
                    Alert(
                        business_id=business.id,
                        kind=AlertKind.RATING_DROP.value,
                        message=(
                            f"{business.name}: rating dropped {drop:.2f} "
                            f"({prev_avg:.2f} → {new_avg:.2f}) within {settings.alert_rating_drop_window_h}h"
                        ),
                        urgent=False,
                    )
                )

    burst_cutoff = now - dt.timedelta(hours=settings.alert_review_burst_window_h)
    # "New" means first seen since the previous snapshot. The very first scrape has
    # no baseline and must not count the business's whole review history as a burst.
    prev_taken = _aware(prev_snapshot.taken_at) if prev_snapshot is not None else None
    recent = 0
    if prev_taken is not None:
        recent = (
            await session.scalar(
                select(func.count())
                .select_from(Review)
                .where(
                    Review.business_id == business.id,
                    Review.first_seen_at >= burst_cutoff,
                    Review.first_seen_at > prev_taken,
                )
            )
            or 0
        )
    if recent >= settings.alert_review_burst_count and not await _has_recent_dup(
        session, business.id, AlertKind.REVIEW_BURST
    ):
        created.append(
            Alert(
                business_id=business.id,
                kind=AlertKind.REVIEW_BURST.value,
                message=(
                    f"{business.name}: {recent} new reviews in "
                    f"{settings.alert_review_burst_window_h}h (total {new_count})"
                ),
                urgent=False,
            )
        )

    for alert in created:
        session.add(alert)
    return created
