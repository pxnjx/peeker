"""ORM models: tracked businesses, reviews, rating snapshots, blocks, alerts."""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow  # noqa: F401  (re-exported for compatibility)


class BusinessKind(str, enum.Enum):  # noqa: UP042 - str-mixin kept for JSON round-trip parity
    OWN = "own"
    COMPETITOR = "competitor"


class BusinessStatus(str, enum.Enum):  # noqa: UP042
    IDLE = "idle"
    QUEUED = "queued"
    SCRAPING = "scraping"
    BACKOFF = "backoff"
    PARKED = "parked"


class Business(Base):
    __tablename__ = "businesses"
    # The scheduler asks "who is idle or in backoff and due right now" every 15 seconds.
    # Indexes are created on every database by _ensure_query_indexes (db/__init__.py);
    # declaring them here too only duplicates the DDL.
    __table_args__: tuple = ()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    maps_url: Mapped[str] = mapped_column(String(768))
    kind: Mapped[str] = mapped_column(String(16), default=BusinessKind.OWN.value)
    status: Mapped[str] = mapped_column(String(16), default=BusinessStatus.IDLE.value)
    # Place profile (filled on scrape from the Maps listing).
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opening_hours: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_blocks: Mapped[int] = mapped_column(Integer, default=0)
    parked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    reviews: Mapped[list[Review]] = relationship(
        back_populates="business",
        cascade="all, delete-orphan",
        order_by="Review.id",
    )
    blocks: Mapped[list[BlockEvent]] = relationship(back_populates="business", cascade="all, delete-orphan")
    alerts: Mapped[list[Alert]] = relationship(back_populates="business", cascade="all, delete-orphan")
    snapshots: Mapped[list[RatingSnapshot]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    performance: Mapped[list[PerformanceRow]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("business_id", "google_review_id", name="uq_review_business_google"),
        # The two recency indexes are created on every database by _ensure_query_indexes
        # (db/__init__.py), which owns the DDL: both review views order by
        # COALESCE(review_time, first_seen_at) DESC, which no plain column index can serve,
        # so SQLite scanned into a temp b-tree on every poll until they existed
        # (4.4ms/call at 1k rows, 0.5ms indexed; reproduce with scripts/idx_test.py).
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    business: Mapped[Business] = relationship(back_populates="reviews")
    google_review_id: Mapped[str] = mapped_column(String(64), index=True)
    author: Mapped[str] = mapped_column(String(255), default="")
    rating: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text, default="")
    review_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RatingSnapshot(Base):
    """Average rating + count captured after each scrape, powers trend charts."""

    __tablename__ = "rating_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    business: Mapped[Business] = relationship(back_populates="snapshots")
    avg_rating: Mapped[float] = mapped_column(Float)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    taken_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PerformanceRow(Base):
    """One period of a Google Business Profile performance CSV (7 tracked metrics)."""

    __tablename__ = "performance_rows"
    __table_args__ = (UniqueConstraint("business_id", "period", name="uq_perf_business_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # NULL → pending: CSV uploaded before this location was tracked; auto-attaches on business create.
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=True)
    business: Mapped[Business | None] = relationship(back_populates="performance")
    source_name: Mapped[str] = mapped_column(String(255), default="", index=True)  # CSV "Location Name"
    period: Mapped[str] = mapped_column(String(64))  # raw CSV label ("2026-01-01", "Week of Jan 5", ...)
    period_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # parsed if possible
    search_mobile: Mapped[int] = mapped_column(Integer, default=0)
    search_desktop: Mapped[int] = mapped_column(Integer, default=0)
    maps_mobile: Mapped[int] = mapped_column(Integer, default=0)
    maps_desktop: Mapped[int] = mapped_column(Integer, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    directions: Mapped[int] = mapped_column(Integer, default=0)
    website_clicks: Mapped[int] = mapped_column(Integer, default=0)
    # Time of the latest upload; displayed as the table's "Period" column.
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BlockEvent(Base):
    """A single anti-bot / block page encountered while scraping."""

    __tablename__ = "block_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    business: Mapped[Business] = relationship(back_populates="blocks")
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    page_url: Mapped[str] = mapped_column(String(768), default="")


class AlertKind(str, enum.Enum):  # noqa: UP042
    RATING_DROP = "rating_drop"
    RATING_DROP_URGENT = "rating_drop_urgent"
    REVIEW_BURST = "review_burst"


class Alert(Base):
    __tablename__ = "alerts"
    # The badge count and the alerts panel both ask for open alerts newest first.
    # The index is created by _ensure_query_indexes (db/__init__.py).
    __table_args__: tuple = ()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    business: Mapped[Business] = relationship(back_populates="alerts")
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    urgent: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seen: Mapped[bool] = mapped_column(default=False)
