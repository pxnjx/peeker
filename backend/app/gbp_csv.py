"""Parse Google Business Profile performance CSV exports (the file downloaded from Google).

Only the seven tracked metrics are kept: Google Search (mobile/desktop), Google Maps
(mobile/desktop), calls, directions and website clicks — messages, bookings, keywords and
other columns are ignored. Header matching is tolerant (case, punctuation, and naming
variants such as "Google Search - Mobile" vs "Views on Search Mobile") so both the
business.google.com export and third-party re-exports parse the same way.

Each row also carries its own location name (the "Location name"/"Business name" column) and, when
present, a store/location code — so account-level exports (one row per location, no period column at
all) can be split per location by the caller. For those exports the row key comes from the date range
in the uploaded file name — see ``period_from_filename``.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
from dataclasses import dataclass

METRIC_KEYS: tuple[str, ...] = (
    "search_mobile",
    "search_desktop",
    "maps_mobile",
    "maps_desktop",
    "calls",
    "directions",
    "website_clicks",
)

_NAME_LABELS = frozenset({"business name", "location name", "page name", "name"})
_CODE_LABELS = frozenset({"store code", "store id", "location id", "branch code", "code"})
_SKIP_PERIODS = frozenset({"total", "totals", "average", "avg", "mean"})
_PERIOD_WORDS = frozenset({"date", "period", "week", "day", "time", "month", "range"})


@dataclass(slots=True)
class ParsedPerformanceRow:
    period: str
    period_date: dt.date | None
    location: str = ""  # per-row "Location name"/"Business name" cell
    code: str = ""  # per-row store/location id when the export has one
    search_mobile: int = 0
    search_desktop: int = 0
    maps_mobile: int = 0
    maps_desktop: int = 0
    calls: int = 0
    directions: int = 0
    website_clicks: int = 0


@dataclass(slots=True)
class ParsedPerformanceCsv:
    business_name: str | None
    rows: list[ParsedPerformanceRow]


def _norm(value: str) -> str:
    """Lowercase and collapse everything but letters/digits to single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _classify(header: str) -> str | None:
    """Map a header cell to one of METRIC_KEYS, or None when it is not a tracked metric."""
    h = _norm(header)
    if not h:
        return None
    if "website" in h and "click" in h:
        return "website_clicks"
    if re.search(r"\bcalls?\b", h):
        return "calls"
    if "direction" in h:
        return "directions"
    has_search = "search" in h
    if not has_search and "map" not in h:
        return None
    if "total" in h or "overall" in h:
        return None
    if "mobile" in h:
        device = "mobile"
    elif "desktop" in h or "computer" in h:
        device = "desktop"
    else:
        device = "desktop"  # "Views on Search"/"Views on Maps" columns are desktop in Google's export
    surface = "search" if has_search else "maps"
    return f"{surface}_{device}"


def _to_int(cell: str) -> int:
    cleaned = cell.replace(",", "").replace("\xa0", " ").strip()
    if not cleaned:
        return 0
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def _parse_date(label: str) -> dt.date | None:
    """Best-effort period → date (ISO, M/D/Y, or 'Jan 5, 2026'); None when unparseable."""
    m = re.search(r"\d{4}-\d{1,2}-\d{1,2}", label)
    if m:
        try:
            y, mo, d = (int(p) for p in m.group(0).split("-"))
            return dt.date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", label)  # Google's US-style export
    if m:
        mo, d, y = (int(p) for p in m.groups())
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", label)
    if m:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt).date()
            except ValueError:
                continue
    return None


_RANGE_RE = re.compile(
    r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*(?:-|–|—|to|_)\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})",
    re.I,
)
_SINGLE_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


def _safe_date(year: str, month: str, day: str) -> dt.date | None:
    try:
        return dt.date(int(year), int(month), int(day))
    except ValueError:
        return None


def period_from_filename(filename: str) -> tuple[str, dt.date | None]:
    """Row key for period-less exports: the date range Google puts in the file name.

    "GMB insights … - 2026-8-1 - 2026-8-31 - <hash>.csv" → ("2026-08-01 – 2026-08-31", 2026-08-31).
    Returns ("", None) when the name carries no date.
    """
    name = os.path.basename(filename or "")
    m = _RANGE_RE.search(name)
    if m:
        start = _safe_date(m.group(1), m.group(2), m.group(3))
        end = _safe_date(m.group(4), m.group(5), m.group(6))
        if start and end:
            return f"{start.isoformat()} – {end.isoformat()}", end
    m = _SINGLE_DATE_RE.search(name)
    if m:
        day = _safe_date(m.group(1), m.group(2), m.group(3))
        if day is not None:
            return day.isoformat(), day
    return "", None


def parse_performance_csv(text: str) -> ParsedPerformanceCsv:
    """Parse a GBP performance CSV. Raises ValueError with a human message on bad input."""
    rows = list(csv.reader(io.StringIO(text)))

    header_idx: int | None = None
    for i, row in enumerate(rows):
        if sum(1 for cell in row if _classify(cell)) >= 2:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            "no performance columns found — expected Google Search/Maps, calls, directions, website clicks"
        )

    header = rows[header_idx]
    col_keys: dict[int, str] = {}
    period_col: int | None = None
    name_col: int | None = None
    code_col: int | None = None
    for j, cell in enumerate(header):
        key = _classify(cell)
        if key is not None:
            if key not in col_keys.values():
                col_keys[j] = key
            continue
        norm = _norm(cell)
        words = set(norm.split())
        if period_col is None and words & _PERIOD_WORDS:
            period_col = j
        if name_col is None and norm in _NAME_LABELS:
            name_col = j
        if code_col is None and norm in _CODE_LABELS:
            code_col = j
    if not col_keys:
        raise ValueError("no tracked metric columns found in the CSV header")
    if period_col is None and name_col is None and code_col is None:
        # No period and no label column at all → keep the legacy guess (first non-metric column).
        period_col = next((j for j in range(len(header)) if j not in col_keys), 0)

    # Business name: title line above the header ("Business name: X"), a label/value pair
    # row, or the per-row location-name column — collided with businesses.name by the caller.
    business_name: str | None = None
    for row in rows[:header_idx]:
        for cell in row[:4]:
            m = re.match(r"\s*(business\s+name|location\s+name|page\s+name|name)\s*[:\-–]\s*(.+)", cell, re.I)
            if m:
                business_name = m.group(2).strip()
                break
        if business_name is None and len(row) >= 2 and _norm(row[0]) in _NAME_LABELS and row[1].strip():
            business_name = row[1].strip()
        if business_name:
            break

    data: list[ParsedPerformanceRow] = []
    period: str
    period_date: dt.date | None
    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            break  # blank line ends the table (keeps keyword sections below out)
        location = row[name_col].strip() if name_col is not None and name_col < len(row) else ""
        code = row[code_col].strip() if code_col is not None and code_col < len(row) else ""
        if period_col is None:
            # Account-level export (one row per location, no period column): the caller keys these
            # rows by the export's date range, and Google's metric-description/legend rows (no
            # name, no code) are dropped here.
            if not location and not code:
                continue
            period, period_date = "", None
        else:
            period = row[period_col].strip() if period_col < len(row) else ""
            if not period or _norm(period) in _SKIP_PERIODS:
                continue
            period_date = _parse_date(period)
        values: dict[str, int] = {}
        for j, key in col_keys.items():
            values[key] = _to_int(row[j]) if j < len(row) else 0
        data.append(
            ParsedPerformanceRow(
                period=period,
                period_date=period_date,
                location=location,
                code=code,
                **values,
            )
        )
        if business_name is None and location:
            business_name = location

    if not data:
        raise ValueError("CSV header found but no data rows")
    return ParsedPerformanceCsv(business_name=business_name, rows=data)
