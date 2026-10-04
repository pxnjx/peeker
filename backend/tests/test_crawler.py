"""Pure-function tests for Google Maps timestamp / number parsing."""
from __future__ import annotations

import datetime as dt
import json

from app.crawler.base import ReviewData
from app.crawler.google_maps import (
    _ALL_REVIEWS_LABEL_RE,
    GoogleMapsCrawler,
    _boq_payload,
    _clean_boq_text,
    _clean_hours,
    _feature_id_from_url,
    _first_float,
    _is_degraded,
    _parse_count,
    _review_list_url,
    _strip_icon_glyphs,
    _want_count,
    parse_when,
)


def test_first_float_uses_comma_as_decimal_separator() -> None:
    assert _first_float("3,9") == 3.9
    assert _first_float("Bintang 4,5 dari 5") == 4.5


def test_first_float_dot_and_plain_integers() -> None:
    assert _first_float("4.7") == 4.7
    assert _first_float("Rated 4 stars") == 4.0
    assert _first_float(None) is None
    assert _first_float("no numbers here") is None


def test_parse_count_parenthesized_summary() -> None:
    assert _parse_count("3,9(39)") == 39
    assert _parse_count("4.7 (1,234 Reviews)") == 1234
    assert _parse_count("39 ulasan") == 39


def test_parse_count_grouping_separators() -> None:
    assert _parse_count("4,7(1.234)") == 1234
    assert _parse_count("") is None
    assert _parse_count(None) is None
    # A bare rating (degraded page without the "(N)" total) is not a count.
    assert _parse_count("3.9") is None
    assert _parse_count("3,9") is None


def test_parse_when_relative_english() -> None:
    expected = dt.datetime.now(dt.UTC) - dt.timedelta(days=60)
    got = parse_when("2 months ago")
    assert got is not None
    assert abs((got - expected).total_seconds()) < 120


def test_parse_when_relative_indonesian() -> None:
    for text, days in (("2 bulan lalu", 60), ("3 hari lalu", 3), ("sebulan yang lalu", 30)):
        expected = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
        got = parse_when(text)
        assert got is not None, text
        assert abs((got - expected).total_seconds()) < 180, text


def test_parse_when_absolute_and_garbage() -> None:
    got = parse_when("Jun 3, 2024")
    assert got is not None
    assert (got.year, got.month, got.day) == (2024, 6, 3)
    assert parse_when("soon™") is None
    assert parse_when(None) is None


def test_is_degraded_only_when_summary_and_reviews_both_missing() -> None:
    assert _is_degraded(None, [])
    # Summary without cards is a valid no-op scrape (avg/count come from the summary).
    assert not _is_degraded({"rating": "3,9", "count": "3,9(39)"}, [])
    # Cards without the summary are enough to derive avg/count.
    assert not _is_degraded(None, [ReviewData("r1", "A", 5.0, "ok", None)])


def test_review_list_url_is_idempotent_and_keeps_query() -> None:
    place = "https://www.google.com/maps/place/UOB/data=!4m6!3m5!16s%2Fabc?hl=en"
    expected = "https://www.google.com/maps/place/UOB/data=!4m6!3m5!9m1!1b1!16s%2Fabc?hl=en"
    assert _review_list_url(place) == expected
    assert _review_list_url(expected) == expected


def test_review_list_url_supports_generic_place_url() -> None:
    assert _review_list_url("https://maps.google.com/?cid=1") == (
        "https://maps.google.com/!9m1!1b1?cid=1"
    )



def test_summarize_degraded_is_why_scrape_must_raise() -> None:
    # _summarize(None, []) would persist avg=0/count=0 → false rating-drop alert;
    # scrape() guards that input via _is_degraded → DegradedError → worker backoff instead.
    assert GoogleMapsCrawler._summarize(None, []) == (0.0, 0)
    assert _is_degraded(None, [])


def test_all_reviews_label_regex_matches_full_list_button() -> None:
    """Regression: _open_full_review_list must find the preview's "all reviews" control."""
    # Indonesian Maps: the button carries the remaining count.
    assert _ALL_REVIEWS_LABEL_RE.search("Lihat ulasan lainnya (34)")
    # English Maps variants.
    assert _ALL_REVIEWS_LABEL_RE.search("See all reviews")
    assert _ALL_REVIEWS_LABEL_RE.search("All reviews (39)")
    # Controls that must NOT be clicked (sort / unrelated buttons).
    assert not _ALL_REVIEWS_LABEL_RE.search("Sort by relevance")
    assert not _ALL_REVIEWS_LABEL_RE.search("Terbaru")


def test_merge_reviews_unions_ids_and_keeps_longer_body() -> None:
    """Pane harvest + review-list harvest must union without losing text."""
    a = [
        ReviewData("r1", "A", 5.0, "preview…", None),
        ReviewData("r2", "B", 4.0, "only in pane", None),
    ]
    b = [
        ReviewData("r1", "A", 5.0, "the fully expanded body", None),
        ReviewData("r3", "C", 1.0, "only in list", None),
    ]
    merged = GoogleMapsCrawler._merge_reviews(a, b)
    by_id = {r.google_review_id: r for r in merged}
    assert set(by_id) == {"r1", "r2", "r3"}
    assert by_id["r1"].text == "the fully expanded body"
    # No duplicates when the second harvest is empty or identical.
    same = GoogleMapsCrawler._merge_reviews(a, list(a))
    assert len(same) == 2


# ---------------------------------------------------------------- review RPC (GetLocalBoqProxy)

_PLACE_URL = (
    "https://www.google.com/maps/place/UOB+Setiabudi+JKT/@-6.2145415,106.8112241,15z/"
    "data=!3m1!5s0x2e69f4081c8168eb:0xf2df253ff848b6bc!4m6!3m5"
    "!1s0x2e69f5049d182e61:0xa17235d7c9141c0!8m2!3m-6.2145415!4m13"
)


def test_feature_id_prefers_hex_feature_id() -> None:
    """The !1s segment is what the review RPC needs; share links embed several ids."""
    assert _feature_id_from_url(_PLACE_URL) == "0x2e69f5049d182e61:0xa17235d7c9141c0"
    # A place id that is a base64 place code is equally valid.
    assert _feature_id_from_url("https://maps.google.com/?cid=1!8m2!1sChIJabc!3m1") == "ChIJabc"
    assert _feature_id_from_url("https://www.google.com/maps") is None


def test_parse_boq_datetime_handles_ms_and_microsecond_epochs() -> None:
    """Live RPC timestamps arrive in milliseconds; some locales use microseconds."""
    ms = GoogleMapsCrawler._boq_to_review(
        {"id": "r1", "author": "A", "rating": 5, "text": "x", "published": 1_729_001_966_504}
    )
    assert ms is not None and ms.review_time is not None
    assert ms.review_time.year == 2024
    micro = GoogleMapsCrawler._boq_to_review(
        {"id": "r2", "author": "B", "rating": 4, "text": "y", "published": 1_729_001_966_504_000}
    )
    assert micro is not None and micro.review_time == ms.review_time
    missing = GoogleMapsCrawler._boq_to_review(
        {"id": "r3", "author": "C", "rating": 4, "text": "y", "published": None}
    )
    assert missing is not None and missing.review_time is None


def test_boq_to_review_cleans_body_and_backfills_missing_id() -> None:
    """RPC bodies are mini-HTML; reviews without a Google id still need a stable key."""
    row = GoogleMapsCrawler._boq_to_review(
        {
            "id": "AfABzpSNhQq0",
            "author": " robi abdul ",
            "rating": 1,
            "text": "pelayanan lama<br>tidak membantu &amp; lambat",
            "published": 1_779_432_230_757,
        }
    )
    assert row is not None
    assert row.google_review_id == "AfABzpSNhQq0"
    assert row.author == "robi abdul"
    assert row.rating == 1.0
    assert row.text == "pelayanan lama\ntidak membantu & lambat"

    anonymous = GoogleMapsCrawler._boq_to_review({"author": "Anon", "rating": 9, "text": "bagus"})
    assert anonymous is not None
    assert anonymous.google_review_id.startswith("anon-")
    assert anonymous.rating == 0.0  # an out-of-range rating must not poison the average
    # Same content → same key, so repeated scrapes upsert instead of duplicating.
    again = GoogleMapsCrawler._boq_to_review({"author": "Anon", "rating": 9, "text": "bagus"})
    assert again is not None and again.google_review_id == anonymous.google_review_id
    assert GoogleMapsCrawler._boq_to_review({"author": "", "rating": 5, "text": ""}) is None


def test_boq_payload_first_page_and_pagination_token() -> None:
    """Page 1 carries pageSize 10 + the place id; continuation swaps in Google's token."""
    first = json.loads(_boq_payload("0x1:0x2", 1))
    assert first[0] is None
    outer, inner = first[1], first[1][9]
    assert outer[:9] == [None] * 9
    assert inner[1] == 1 and inner[9] == 10 and inner[11] == ["0x1:0x2"]

    nxt = json.loads(_boq_payload("0x1:0x2", 2, "TOKEN"))
    inner2 = nxt[1][9]
    assert inner2[1] == 2 and inner2[11] == ["0x1:0x2"] and inner2[-1] == "TOKEN"
    # Google's RPC is posted in the URL: no whitespace is allowed in the payload.
    assert " " not in _boq_payload("0x1:0x2", 1)


def test_clean_boq_text_renders_line_breaks_and_entities() -> None:
    assert _clean_boq_text("a<br>b<br/>c") == "a\nb\nc"
    assert _clean_boq_text("<b>kotor</b> &quot;petik&quot;") == 'kotor "petik"'
    assert _clean_boq_text(None) == ""


def test_clean_hours_turns_icon_glyphs_into_one_line_per_day() -> None:
    """Live UOB Setiabudi value: glued day cells separated by Material-Symbols glyphs."""
    raw = "SundayClosed\ue14dMonday8.00\u202fam\u20133.00\u202fpm\ue14dTuesday8.00 am\u20133.00 pm"
    assert _clean_hours(raw) == (
        "Sunday\tClosed\nMonday\t8.00 am\u20133.00 pm\nTuesday\t8.00 am\u20133.00 pm"
    )
    # aria-label variant: comma separated, no glyphs at all.
    assert _clean_hours("HoursSunday Closed, Monday 8:00 AM \u2013 3:00 PM") == (
        "Sunday\tClosed\nMonday\t8:00 AM \u2013 3:00 PM"
    )
    assert _clean_hours("") == ""
    # Free text (other locale / note) survives as one clean line instead of vanishing.
    assert _clean_hours("\ue14fTemporarily closed") == "Temporarily closed"


def test_strip_icon_glyphs_removes_unrenderable_private_use_characters() -> None:
    assert _strip_icon_glyphs("Bank \ue14d  Jakarta  Selatan") == "Bank Jakarta Selatan"
    assert _strip_icon_glyphs("(021) 5210035") == "(021) 5210035"


def test_want_count_caps_google_total_by_scrape_limit() -> None:
    assert _want_count(100, 39) == 39
    assert _want_count(20, 39) == 20
    assert _want_count(100, None) == 100
    assert _want_count(100, 0) == 100
