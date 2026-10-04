"""Pydantic schemas for the HTTP API."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class BusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    maps_url: HttpUrl
    kind: str = Field(default="own", pattern="^(own|competitor)$")
    enqueue: bool = True  # queue the first scrape immediately


class BusinessUpdate(BaseModel):
    """Partial update — the fields the edit dialog exposes: display name and the Maps link.

    Both optional so a patch carries only what changed (e.g. a fixed URL without retyping
    the name); the endpoint rejects a patch that carries nothing.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    maps_url: HttpUrl | None = None


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    maps_url: str
    kind: str
    avg_rating: float | None = None  # latest snapshot; None until first scrape
    review_count: int | None = None
    status: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    category: str | None = None
    opening_hours: str | None = None
    next_due_at: dt.datetime | None
    # Taken from the latest rating snapshot: written once per successful scrape,
    # so this is when the crawler last read the listing. None until first scrape.
    last_scraped_at: dt.datetime | None = None
    consecutive_blocks: int
    parked_until: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    business_name: str
    google_review_id: str
    author: str
    rating: float
    text: str
    review_time: dt.datetime | None
    first_seen_at: dt.datetime


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    avg_rating: float
    review_count: int
    taken_at: dt.datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    kind: str
    message: str
    urgent: bool
    created_at: dt.datetime
    seen: bool


class SeenAllOut(BaseModel):
    """How many open alerts the 'mark all seen' action closed."""

    updated: int


class StatsOut(BaseModel):
    businesses: int
    queued: int
    scraping: int
    idle: int
    backoff: int
    parked: int
    reviews: int
    open_alerts: int


class PerformanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    source_name: str  # CSV location/business name of the upload that produced this row
    period: str
    period_date: dt.date | None
    search_mobile: int
    search_desktop: int
    maps_mobile: int
    maps_desktop: int
    calls: int
    directions: int
    website_clicks: int
    imported_at: dt.datetime


class PerformanceUploadOut(BaseModel):
    business_id: int | None  # None → stored pending under business_name (or split per location)
    business_name: str
    matched: bool  # False → nothing attached; rows stay pending until that business exists
    imported: int
    periods: list[str]
    attached_locations: list[str]  # CSV location names that landed on a tracked business
    pending_locations: list[str]  # CSV location names stored pending (business not tracked yet)
