"""Crawler protocol + scrape result types."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class BlockedError(RuntimeError):
    """Raised when Google serves a block page / CAPTCHA instead of reviews."""


class DegradedError(RuntimeError):
    """Raised when Maps renders neither the rating summary nor review cards (soft-limited / not hydrated)."""


@dataclass
class ReviewData:
    google_review_id: str
    author: str
    rating: float
    text: str
    review_time: datetime | None


@dataclass
class ScrapeResult:
    business_url: str
    avg_rating: float
    review_count: int
    reviews: list[ReviewData] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(dt.UTC))
    # Optional place profile from the Maps listing (address / phone / website / category / hours).
    address: str = ""
    phone: str = ""
    website: str = ""
    category: str = ""
    opening_hours: str = ""


class Crawler(Protocol):
    """Anything the worker can hand a business URL to and get reviews back."""

    async def scrape(self, url: str) -> ScrapeResult: ...

