"""Crawler subpackage: Playwright-based Google Maps review scraper with anti-detect hardening."""
from __future__ import annotations

from ..config import Settings, get_settings
from . import base
from .google_maps import GoogleMapsCrawler

__all__ = ["GoogleMapsCrawler", "base", "get_crawler", "Settings"]

_cache: GoogleMapsCrawler | None = None


def get_crawler(settings: Settings | None = None) -> GoogleMapsCrawler:
    """Process-wide crawler (one shared browser context)."""
    global _cache
    if _cache is None:
        _cache = GoogleMapsCrawler(settings or get_settings())
    return _cache


async def close_crawler() -> None:
    global _cache
    if _cache is not None:
        await _cache.close()
        _cache = None

