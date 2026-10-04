"""Pure parsing helpers for Google Maps review scraping.

No Playwright imports: everything here is string / URL / datetime work that
can be unit-tested without a browser.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from typing import Any

from .base import ReviewData

_RELATIVE_UNITS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2_592_000,
    "year": 31_536_000,
    # Indonesian UI fallback ("2 bulan lalu") in case hl=en is unavailable.
    "detik": 1,
    "menit": 60,
    "jam": 3600,
    "hari": 86400,
    "minggu": 604800,
    "bulan": 2_592_000,
    "tahun": 31_536_000,
}



def parse_when(text: str | None) -> dt.datetime | None:
    """Parse Maps review timestamps: relative ("2 months ago"/"2 bulan lalu") or absolute ("Jun 3, 2024")."""
    if not text:
        return None
    t = text.strip().lower()
    m = re.match(r"(?:(\d+)|a|an)\s+(second|minute|hour|day|week|month|year)s?\s+ago", t)
    if m:
        n = int(m.group(1) or 1)
        return dt.datetime.now(dt.UTC) - dt.timedelta(seconds=n * _RELATIVE_UNITS[m.group(2)])
    m_id = re.match(
        r"(?:(\d+)|se\w*)?\s*(?:\w+\s+)?(detik|menit|jam|hari|minggu|bulan|tahun)\s*(?:yang\s+)?lalu",
        t,
    )
    if m_id:
        n = int(m_id.group(1) or 1)
        return dt.datetime.now(dt.UTC) - dt.timedelta(seconds=n * _RELATIVE_UNITS[m_id.group(2)])
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y %H:%M"):
        try:
            return dt.datetime.strptime(text.strip(), fmt).replace(tzinfo=dt.UTC)
        except ValueError:
            continue
    return None



def _feature_id_from_url(url: str) -> str | None:
    """Feature/place id from a Maps place URL: the ``!1s`` segment (``0x…:0x…`` or ChIJ…).

    Mirrors google-maps-review-scraper's extraction (matches in order, second match first),
    but prefers an explicit ``0x…:0x…`` feature id when several ``!1s`` segments exist
    (share links embed more than one).
    """
    matches = re.findall(r"!1s([A-Za-z0-9_:]+)!", url)
    for cand in matches:
        if re.fullmatch(r"0x[0-9a-fA-F]+:0x[0-9a-fA-F]+", cand):
            return cand
    if len(matches) > 1:
        return matches[1]
    return matches[0] if matches else None


def _parse_boq_datetime(value: object) -> dt.datetime | None:
    """BOQ review timestamps are epoch numbers whose unit is unknown: ms or µs in practice."""
    try:
        n = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    if n > 10**14:
        n //= 1_000_000  # microseconds
    elif n > 10**11:
        n //= 1_000  # milliseconds
    return dt.datetime.fromtimestamp(n, tz=dt.UTC) if n > 0 else None


def _stable_anon_review_id(author: str, text: str, published: object) -> str:
    """Deterministic key for reviews without a Google id — stable across scrapes."""
    digest = hashlib.sha256(f"{author}|{text}|{published}".encode()).hexdigest()[:24]
    return f"anon-{digest}"

def _clean_boq_text(raw: str | None) -> str:
    """BOQ bodies are mini-HTML: ``<br>`` separates lines and entities are escaped."""
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


# Material Symbols icons that Maps renders *inside* textContent live in the private-use area
_ICON_GLYPH_RE = re.compile(r"[\ue000-\uf8ff\U000f0000-\U0010fffd]")
_WEEKDAY = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
_WEEKDAY_SPLIT_RE = re.compile(rf"(?=(?:{_WEEKDAY})\b)", re.I)
_WEEKDAY_VALUE_RE = re.compile(rf"(?i)^({_WEEKDAY})[. :]?\s*(.*)$")


def _strip_icon_glyphs(raw: str) -> str:
    """Drop icon glyphs from a place-profile cell and collapse the whitespace they leave behind."""
    return re.sub(r"\s+", " ", _ICON_GLYPH_RE.sub(" ", raw)).strip()


def _clean_hours(raw: str) -> str:
    """Google's hours arrive glued into one string with icon glyphs between day cells.

    ``"SundayClosed\ue14dMonday8.00\u202fam–3.00\u202fpm"`` becomes one readable line per day
    (``"Sunday\\tClosed\\nMonday\\t8.00 am–3.00 pm"``). Text without weekday names (other locales,
    "Open now" notes) is kept as cleaned free text instead of being dropped.
    """
    if not raw:
        return ""
    lines: list[str] = []
    for chunk in _ICON_GLYPH_RE.sub("\n", raw).replace("\u00a0", " ").split("\n"):
        chunk = re.sub(r"(?i)^hours[:.\s]*", "", chunk.strip())
        for piece in _WEEKDAY_SPLIT_RE.split(chunk):
            piece = re.sub(r"\s+", " ", piece).strip(" ,;\t-–")
            if not piece:
                continue
            match = _WEEKDAY_VALUE_RE.match(piece)
            lines.append(f"{match.group(1).capitalize()}\t{match.group(2)}".rstrip() if match else piece)
    return "\n".join(lines) if lines else re.sub(r"\s+", " ", raw).strip()




def _boq_payload(feature_id: str, sort_order: int, token: str = "") -> str:
    """Request body for Google's ``GetLocalBoqProxy`` review RPC.

    Layout (from google-maps-review-scraper): ``[null, [null×9, [...]]]`` where the inner
    array carries sortOrder (1 = most relevant, 2 = newest, 3 = highest, 4 = lowest),
    page size 10, the feature/place id, and — for continuation pages — the token Google
    returns at ``data[1][10][6]``.
    """
    inner: list[Any]
    if not token:
        inner = [None, sort_order, None, None, None, None, None, None, None, 10, None, [feature_id]]
    else:
        inner = [
            None,
            sort_order,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            [feature_id],
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            token,
        ]
    return json.dumps([None, [None] * 9 + [inner]], separators=(",", ":"))


def _review_list_url(url: str) -> str:
    """Return the Maps place URL in its explicit full-review-list view.

    ``!9m1!1b1`` is part of Google's public review-link format (not a private API). Keep it in the
    path before the query string and make repeated calls idempotent, so a retry never appends it twice.
    """
    base, sep, query = url.partition("?")
    base = re.sub(r"!9m1!1b1(?=!|$)", "", base)
    if "!9m1!1b1" not in base:
        # Maps' encoded place id is the !16s… segment; the public review-list flag belongs just
        # before it (…!9m1!1b1!16s…). Generic short/place URLs still receive a valid trailing flag.
        marker = base.rfind("!16s")
        base = base[:marker] + "!9m1!1b1" + base[marker:] if marker > 0 else base + "!9m1!1b1"
    return base + sep + query



def _first_float(text: str | None) -> float | None:
    """First number in text; a comma is a decimal separator (id-ID renders the rating as "3,9")."""
    if not text:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    return float(m.group(0).replace(",", ".")) if m else None


def _parse_count(text: str | None) -> int | None:
    """Review total from summary text like "3,9(39)", "4.7 (1,234 Reviews)" or "1.234 ulasan"."""
    if not text:
        return None
    paren = re.search(r"\(([\d.,\s]+)\)", text)
    nums = re.findall(r"\d[\d.,]*", text)
    if paren and paren.group(1).strip():
        token = paren.group(1).strip()
    elif nums:
        token = max(nums, key=len)
    else:
        return None
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        token = re.sub(r"[.,]", "", token)
    elif re.fullmatch(r"\d+[.,]\d{1,2}", token):
        return None  # a rating like "3.9", not a count
    else:
        token = re.sub(r"\D", "", token)
    return int(token) if token else None


def _is_degraded(summary: dict | None, reviews: list[ReviewData]) -> bool:  # type: ignore[type-arg]
    """Neither the rating block nor a single review card → a soft-degraded render, not real data."""
    return summary is None and not reviews


def _want_count(max_reviews: int, expected: int | None) -> int:
    """How many reviews are worth chasing: Google's own total, capped by the per-scrape limit."""
    return min(max_reviews, expected) if expected else max_reviews




# Public affordance labels (ID + EN Maps locales) for the full review-list control.
_ALL_REVIEWS_LABEL_RE = re.compile(
    r"lihat\s+ulasan\s+lainnya|see\s+all\s+reviews|all\s+reviews", re.I
)
