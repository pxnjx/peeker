"""Playwright-based Google Maps review scraper with anti-detect hardening."""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import random
import re
import time
from typing import Any

from playwright.async_api import Browser, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..config import Settings, get_settings
from .base import BlockedError, DegradedError, ReviewData, ScrapeResult

log = logging.getLogger(__name__)

from .page_scripts import (
    _BOQ_ENDPOINT,
    _BOQ_FETCH_JS,
    _END_SENTINEL_JS,
    _EXPAND_MORE_JS,
    _EXTRACT_CARD_JS,
    _SCROLL_FEED_JS,
    _TABS_JS,
    _WHEEL_JS,
    _WHEEL_TARGET_JS,
)
from .parsing import (
    _ALL_REVIEWS_LABEL_RE,
    _boq_payload,
    _clean_boq_text,
    _clean_hours,
    _feature_id_from_url,
    _first_float,
    _is_degraded,
    _parse_boq_datetime,
    _parse_count,
    _review_list_url,
    _stable_anon_review_id,
    _strip_icon_glyphs,
    _want_count,
    parse_when,
)

__all__ = [
    "GoogleMapsCrawler",
    "parse_when",
]

# Markers that indicate Google served an anti-bot interstitial instead of the place page.
_BLOCK_MARKERS = (
    "unusual traffic",
    "our systems have detected",
    "verify you are human",
    "don't recognize your network",
    "recaptcha",
)

async def _evaluate(  # noqa: ANN201
    page: Page, expression: str, arg: Any = None, *, timeout_s: float = 12.0
):
    """Bounded ``page.evaluate`` — Playwright's raw evaluate has no timeout, so a busy or
    stuck Maps renderer hangs the *entire* scrape (observed live: renderer spinning on CPU
    while every caller waited forever). Returns ``None`` on timeout; callers treat that
    like "JS did not answer" and fall back instead of blocking.

    The pending Playwright op is left to finish (or fail) on its own rather than
    cancelled, so the transport never sees an interrupted write.
    """
    coro = page.evaluate(expression, arg) if arg is not None else page.evaluate(expression)
    task = asyncio.ensure_future(coro)
    done, _ = await asyncio.wait({task}, timeout=timeout_s)
    if not done:
        task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
        log.debug("evaluate timed out after %.0fs", timeout_s)
        return None
    return task.result()


class GoogleMapsCrawler:
    """Scrapes rating summary + reviews from a Google Maps place URL.

    The browser starts lazily on first scrape so importing the app never
    requires an installed browser. One shared browser is reused; each scrape
    opens a fresh context (cookies persist on the browser level).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    async def _wait_hydrated(self, page: Page, timeout_s: float = 8.0) -> None:
        """Wait until the place page is a full render: rating block with a ``(count)`` total,
        or the tab strip / review cards being present.

        A fixed post-navigation sleep is not enough: the rating can appear seconds before the
        count and tabs do, and acting in that window reads a count-less summary (``3.9`` without
        ``(39)``) and finds no reviews tab — the degraded path that used to fail whole scrapes.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                summary = await page.eval_on_selector(
                    "div.F7nice", "el => (el.textContent || '')"
                )
                if "(" in summary:
                    return
                if await page.locator('[role="tab"], div[data-review-id]').count() > 0:
                    return
            except PlaywrightError:
                pass
            with contextlib.suppress(PlaywrightError):
                await page.wait_for_timeout(400)

    async def _open_full_review_list(self, page: Page) -> bool:
        """Expand the public Maps preview into the full review-list view.

        Order matters (learned from live probes): navigating to the ``!9m1!1b1`` flag URL first
        frequently yields a shell render — generic "Google Maps" title, no place UI — while the
        public ``See all reviews``/``Lihat ulasan lainnya`` control reliably opens the list,
        but only after the preview is scrolled, since the control sits below the cards.
        The flag URL is therefore a last resort when no cards rendered at all, and its render
        is verified with recovery back to the previous view when it breaks.
        """
        current = page.url

        # 1) Button path: reveal the control below the preview, then click it.
        if await self._count_cards(page):
            for _ in range(3):
                with contextlib.suppress(PlaywrightError):
                    await _evaluate(page, _SCROLL_FEED_JS)
                    await page.wait_for_timeout(400)
            labels = _ALL_REVIEWS_LABEL_RE
            candidates = (
                page.get_by_role("button", name=labels),
                page.get_by_role("link", name=labels),
                page.locator(
                    'button:has-text("Lihat ulasan lainnya"), a:has-text("Lihat ulasan lainnya"),'
                    ' div[role="button"]:has-text("Lihat ulasan lainnya"),'
                    ' button:has-text("See all reviews"), a:has-text("See all reviews"),'
                    ' div[role="button"]:has-text("See all reviews"),'
                    ' div[role="button"]:has-text("All reviews")'
                ),
            )
            for locator in candidates:
                try:
                    target = locator.first
                    if not await target.count() or not await target.is_visible():
                        continue
                    await target.click(timeout=4_000)
                    log.debug("clicked the public all-reviews control")
                    return await self._wait_for_cards(page, timeout_s=8.0)
                except (PlaywrightError, PlaywrightTimeoutError):
                    continue
            # No control found — the pane may already be the full list; the collector
            # paginates it by scrolling, so keep this view rather than risk a navigation.
            log.debug("no see-all control visible; keeping the current review view")
            return await self._wait_for_cards(page, timeout_s=3.0)

        # 2) Last resort: no cards rendered at all → explicit review-list URL.
        requested = _review_list_url(current)
        if requested != current:
            try:
                await page.goto(requested, wait_until="domcontentloaded")
                await page.wait_for_timeout(random.randint(900, 1_500))
                await self._check_block(page)
                await self._wait_hydrated(page)
                if (
                    await self._count_cards(page) == 0
                    and await page.locator("div.F7nice").count() == 0
                ):
                    # The flag navigation yielded a shell render — recover to the view that
                    # at least had the place summary instead of scraping an empty document.
                    log.debug("full review-list URL broke the render; returning to previous view")
                    with contextlib.suppress(PlaywrightError):
                        await page.goto(current, wait_until="domcontentloaded")
                        await page.wait_for_timeout(random.randint(900, 1_500))
                        await self._wait_hydrated(page)
            except PlaywrightTimeoutError:
                log.debug("full review-list navigation timed out; keeping current view")
        return await self._wait_for_cards(page, timeout_s=3.0)

    async def _goto_review_list(self, page: Page) -> bool:
        """Navigate (or reload) into the explicit ``!9m1!1b1`` full-review-list view.

        The tabbed Reviews pane can stay on a capped preview even after its tab is open
        (live: 5 of 39 cards on the UOB Setiabudi listing), while this view paginates on
        trusted scroll input. False when the navigation times out or the render breaks
        (the previous view is restored in that case).
        """
        current = page.url
        requested = _review_list_url(current)
        # Navigate even when the URL already carries the flag: clicking the Reviews tab
        # rewrites the address bar to include !9m1!1b1 itself, yet the pane can still be
        # the capped preview — a fresh load of the list view resets the feed so it
        # paginates (live probe: same URL, wheel then grew the card count).
        try:
            await page.goto(requested, wait_until="domcontentloaded")
            await page.wait_for_timeout(random.randint(900, 1_500))
            await self._check_block(page)
            await self._wait_hydrated(page)
        except PlaywrightTimeoutError:
            log.info("review-list navigation timed out; keeping current view")
            return False
        if await self._count_cards(page) == 0 and await page.locator("div.F7nice").count() == 0:
            log.info("full review-list URL broke the render; returning to previous view")
            with contextlib.suppress(PlaywrightError):
                await page.goto(current, wait_until="domcontentloaded")
                await page.wait_for_timeout(random.randint(900, 1_500))
                await self._wait_hydrated(page)
            return False
        log.info("full review-list view ready (%d cards)", await self._count_cards(page))
        return True

    @staticmethod
    def _merge_reviews(first: list[ReviewData], second: list[ReviewData]) -> list[ReviewData]:
        """Union two harvests by review id, keeping the longer body per review."""
        merged: dict[str, ReviewData] = {r.google_review_id: r for r in first}
        for r in second:
            prev = merged.get(r.google_review_id)
            if prev is None or len(r.text) > len(prev.text):
                merged[r.google_review_id] = r
        return list(merged.values())

    # ---------------------------------------------------------------- lifecycle
    async def _ensure_started(self) -> Browser:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        self._pw = await async_playwright().start()
        kwargs: dict = {"headless": self.settings.crawler_headless}
        if self.settings.crawler_headless and self.settings.crawler_new_headless:
            # Chrome's "new" headless still renders the tabbed Maps UI; legacy headless gets a
            # reduced page without the Ulasan/Reviews tab, so reviews beyond the preview never load.
            kwargs["headless"] = False
            kwargs["args"] = ["--headless=new"]
        channel = self.settings.crawler_channel
        if channel and channel != "chromium":
            kwargs["channel"] = channel
        if self.settings.crawler_executable_path:
            kwargs.pop("channel", None)
            kwargs["executable_path"] = self.settings.crawler_executable_path
        if self.settings.crawler_proxy_url:
            kwargs["proxy"] = {"server": self.settings.crawler_proxy_url}
        try:
            self._browser = await self._pw.chromium.launch(**kwargs)
        except PlaywrightError:
            # Fall back to bundled chromium / the plain headless mode if the channel or the
            # "--headless=new" flag is unavailable.
            kwargs.pop("channel", None)
            kwargs.pop("executable_path", None)
            kwargs.pop("args", None)
            kwargs["headless"] = self.settings.crawler_headless
            self._browser = await self._pw.chromium.launch(**kwargs)
        return self._browser

    async def close(self) -> None:
        # Shutdown must never raise. The driver object only exposes `stop()` (it has no
        # `close()`), so each handle is released with its own method — otherwise the
        # AttributeError would be swallowed and the driver subprocess would outlive the crawler.
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                await self._pw.stop()
        self._browser = None
        self._pw = None


    async def _new_page(self) -> Page:
        browser = await self._ensure_started()
        lo = self.settings.crawler_viewport_min_width
        hi = self.settings.crawler_viewport_max_width
        context = await browser.new_context(
            viewport={"width": random.randint(lo, hi), "height": 900},
            locale=self.settings.crawler_locale,
            timezone_id=self.settings.crawler_timezone,
        )
        # Hide the CDP automation flag. Google reacts to navigator.webdriver by serving a
        # thinner review pane: with it visible no review content RPC was ever issued while
        # scrolling, with it hidden the pane's infinite-scroll fetch fired (live probes).
        await context.add_init_script(
            "Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined });"
        )
        if self.settings.crawler_block_images:

            async def _filter(route):  # noqa: ANN001
                if route.request.resource_type in ("image", "media", "font"):
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", _filter)
        page = await context.new_page()
        page.set_default_timeout(self.settings.crawler_timeout_ms)
        page.set_default_navigation_timeout(self.settings.crawler_navigation_timeout_ms)
        return page

    # ------------------------------------------------------------------ scraping
    async def scrape(self, url: str) -> ScrapeResult:
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(random.randint(600, 1400))
            await self._check_block(page)
            await self._wait_hydrated(page)
            await self._force_english(page)
            await self._wait_hydrated(page)
            # Read the summary before _open_reviews: div.F7nice can disappear once the
            # Reviews tab replaces the overview pane.
            summary_data = await self._read_summary(page)
            details = await self._read_place_details(page)
            expected = _parse_count(summary_data.get("count")) if summary_data else None
            feature_id = _feature_id_from_url(page.url)

            async def _through_rpc() -> list[ReviewData]:
                """RPC harvest for the current render; empty when no place id is available."""
                if not feature_id:
                    return []
                return await self._collect_reviews_via_boq(page, feature_id, target=expected)

            # Primary strategy: Google's own review RPC. The rendered feed mounts a capped
            # preview (live: 5 cards of 39 on the UOB Setiabudi listing) while the RPC paginates
            # the complete list, so the slow scroll loop is skipped whenever the RPC answers.
            reviews = await _through_rpc()
            if len(reviews) < _want_count(self.settings.crawler_max_reviews, expected):
                await self._open_reviews(page)
                await self._open_full_review_list(page)
                reviews = self._merge_reviews(
                    reviews, await self._collect_reviews(page, target=expected)
                )

            if not reviews and expected != 0:
                # Nothing rendered at all (Google served a reduced page). One clean reload fixes most
                # of these — this is the path that used to leave a business with 5-6 reviews only.
                log.warning("no reviews found for %d expected — reloading once", expected or -1)
                with contextlib.suppress(PlaywrightTimeoutError):
                    await page.reload(wait_until="domcontentloaded")
                await page.wait_for_timeout(random.randint(800, 1_400))
                await self._check_block(page)
                await self._wait_hydrated(page)
                summary_data = await self._read_summary(page) or summary_data
                expected = (
                    _parse_count(summary_data.get("count")) if summary_data else expected
                )
                reviews = await _through_rpc()
                if len(reviews) < _want_count(self.settings.crawler_max_reviews, expected):
                    await self._open_reviews(page)
                    await self._open_full_review_list(page)
                    reviews = self._merge_reviews(
                        reviews, await self._collect_reviews(page, target=expected)
                    )

            # The tabbed Reviews pane can serve a capped preview. The explicit !9m1!1b1
            # review-list view is the one that paginates on trusted scroll — switch to it
            # whenever both the RPC and the pane stopped short of Google's own review total.
            want = _want_count(self.settings.crawler_max_reviews, expected)
            if reviews and len(reviews) < want:
                log.info(
                    "pane yielded %d/%s — switching to the full review-list view",
                    len(reviews),
                    expected or "?",
                )
                if await self._goto_review_list(page):
                    merged = self._merge_reviews(
                        reviews, await self._collect_reviews(page, target=expected)
                    )
                    reviews = merged[: self.settings.crawler_max_reviews]

            if _is_degraded(summary_data, reviews):
                # Persisting this would write avg=0/count=0 and fire a false rating-drop alert.
                raise DegradedError("no rating summary and no review cards (soft-limited or not hydrated)")
            if summary_data is not None and expected is None and not reviews:
                # A rating without a parsable review total and no cards is a partial render; saving
                # it would record count=0 for a place that plainly has reviews.
                raise DegradedError("rating rendered without a review count and no review cards")
            avg_rating, review_count = self._summarize(summary_data, reviews)
            return ScrapeResult(
                business_url=url,
                avg_rating=avg_rating,
                review_count=review_count,
                reviews=reviews,
                scraped_at=dt.datetime.now(dt.UTC),
                address=details.get("address") or "",
                phone=details.get("phone") or "",
                website=details.get("website") or "",
                category=details.get("category") or "",
                opening_hours=details.get("opening_hours") or "",
            )
        finally:
            with contextlib.suppress(Exception):
                await page.context.close()

    async def _check_block(self, page: Page) -> None:
        lowered = page.url.lower()
        if "/sorry/" in lowered or "recaptcha" in lowered:
            raise BlockedError(f"block page URL: {page.url}")
        try:
            body = (await page.inner_text("body", timeout=3_000))[:4_000].lower()
        except PlaywrightTimeoutError:
            body = ""
        if any(marker in body for marker in _BLOCK_MARKERS):
            raise BlockedError(f"block marker found on {page.url}")
        try:
            if await page.locator('iframe[src*="recaptcha"]').count() > 0:
                raise BlockedError("recaptcha iframe present")
        except PlaywrightError:
            pass

    async def _force_english(self, page: Page) -> None:
        """Re-navigate with hl=en.

        Indonesian IPs get lang=id ("Ulasan" tabs, "Bintang" aria-labels, "bulan lalu"
        dates) regardless of the browser locale, which breaks the EN selectors.
        """
        url = page.url
        if "google." not in url or re.search(r"[?&]hl=", url):
            return
        sep = "&" if "?" in url else "?"
        try:
            await page.goto(f"{url}{sep}hl=en", wait_until="domcontentloaded")
            await page.wait_for_timeout(random.randint(500, 900))
        except PlaywrightTimeoutError:
            log.debug("hl=en navigation timed out; continuing")
            return
        await self._check_block(page)

    async def _open_reviews(self, page: Page) -> bool:
        """Open the reviews tab/pane and wait for its cards. True when cards are on screen.

        The tab is matched by ARIA role (EN "Reviews" / ID "Ulasan", whatever element type it is):
        the tabbed layout Google serves uses a plain ``<a role="tab">``, which the previous
        text/div/button selectors missed — that left every scrape with only the ~6 inline preview
        cards of the overview pane (39/86 reviews on Google, 5-6 stored here).
        """
        if await self._reviews_pane_active(page):
            return True
        candidates = (
            page.get_by_role("tab", name=re.compile(r"ulasan|reviews", re.I)),
            page.locator('[role="tab"][aria-label*="Ulasan" i], [role="tab"][aria-label*="Review" i]'),
            page.locator('[role="tab"]:has-text("Ulasan")'),
            page.locator('[role="tab"]:has-text("Reviews")'),
            page.locator("div.F7nice"),  # the header rating block ("3,9 (39)") opens the list
            page.get_by_role("button", name=re.compile(r"ulasan|reviews|all reviews", re.I)),
            page.locator('button[aria-label*="Ulasan" i], button[aria-label*="Review" i]'),
            page.locator(
                'div[aria-label*="Ulasan" i][role="button"], div[aria-label*="Review" i][role="button"]'
            ),
        )
        for loc in candidates:
            try:
                target = loc.first
                if not await target.count() or not await target.is_visible():
                    continue
                await target.click(timeout=3_000)
            except (PlaywrightTimeoutError, PlaywrightError):
                continue
            if await self._wait_for_cards(page, timeout_s=9.0):
                # Cards on screen ⇒ the pane is open. Do NOT require count growth here: the
                # overview preview is capped (~10 cards) and only _open_full_review_list /
                # _collect_reviews expand it. The old "no growth ⇒ Escape and keep trying"
                # dismissal closed the pane that had just opened, leaving every scrape at
                # the 5-unique-card preview.
                await self._poke_end_sentinel(page)  # best-effort; harmless when capped
                log.info("reviews pane opened; cards on screen")
                return True
            # Nothing rendered (a menu/dialog may have opened instead): dismiss and keep trying.
            for _ in range(2):
                with contextlib.suppress(PlaywrightError):
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(250)
        if await self._poke_end_sentinel(page):
            log.info("reviews list expanded without a dedicated pane")
            return True
        if await self._wait_for_cards(page, timeout_s=6.0):
            log.warning("reviews pane did not open; harvesting the inline preview only")
            return True
        return False

    async def _poke_end_sentinel(self, page: Page) -> bool:
        """Move the last visible card into view a couple of times; True when more cards loaded."""
        try:
            before = await _evaluate(page, _END_SENTINEL_JS)
        except PlaywrightError:
            return False
        if before is None:  # renderer too busy to answer — treat as no movement
            return False
        for _ in range(6):
            await page.wait_for_timeout(700)
            try:
                now = await _evaluate(page, _END_SENTINEL_JS)
            except PlaywrightError:
                return False
            if now is not None and now > before:
                return True
        return False

    async def _count_cards(self, page: Page) -> int:
        try:
            return await page.locator("div[data-review-id]").count()
        except PlaywrightError:
            return 0

    async def _reviews_pane_active(self, page: Page) -> bool:
        """True when the reviews tab is the selected one (the pane, not the overview preview)."""
        try:
            tabs = await _evaluate(page, _TABS_JS)
        except PlaywrightError:
            return False
        return bool(tabs) and bool(re.search(r"ulasan|reviews", tabs, re.I))

    async def _wait_for_cards(self, page: Page, timeout_s: float) -> bool:
        """Poll for cards: the pane hydrates asynchronously and can take seconds after a click."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if await self._count_cards(page) > 0:
                return True
            with contextlib.suppress(PlaywrightError):
                await page.wait_for_timeout(400)
        return False

    async def _collect_reviews(
        self, page: Page, max_reviews: int | None = None, target: int | None = None
    ) -> list[ReviewData]:
        """Harvest every card the virtualized feed renders, up to `target` (Google's own count)."""
        max_reviews = max_reviews or self.settings.crawler_max_reviews
        want = max_reviews if not target else min(max_reviews, target)
        feed_selector = await self._find_review_feed(page)
        # The feed is virtualized: cards are removed from the DOM as they scroll
        # out of view, so harvest on every round instead of once at the end.
        collected: dict[str, dict] = {}  # type: ignore[type-arg]
        stale_rounds = 0
        empty_rounds = 0
        last_size = -1
        log.info("collecting reviews: want=%d feed=%s", want, feed_selector or "none")
        for _ in range(80):
            try:
                # Expand collapsed bodies first so textContent is the full comment, not the "…" preview.
                with contextlib.suppress(PlaywrightError):
                    await _evaluate(page, _EXPAND_MORE_JS)
                    await page.wait_for_timeout(120)
                visible = await page.locator("div[data-review-id]").count()
                if visible == 0:
                    raw: list[dict] = []  # type: ignore[type-arg]
                else:
                    raw = await page.eval_on_selector_all("div[data-review-id]", _EXTRACT_CARD_JS)
            except PlaywrightTimeoutError:
                log.warning("review nodes disappeared during extraction")
                break
            for item in raw:
                rid = (item.get("id") or "").strip()
                if not rid:
                    rid = _stable_anon_review_id(
                        item.get("author") or "", item.get("text") or "", item.get("when")
                    )
                prev = collected.get(rid)
                # Keep the longest body: the first pass often still sees the "…" preview.
                if prev is None or len((item.get("text") or "").strip()) > len(
                    (prev.get("text") or "").strip()
                ):
                    collected[rid] = item
            if len(collected) >= want:
                break
            if not collected:
                # Keep waiting for the first cards to hydrate — but bounded: a
                # soft-limited render that never shows cards used to burn all 80 rounds.
                empty_rounds += 1
                if empty_rounds >= 15:
                    break
            elif len(collected) == last_size:
                stale_rounds += 1
                if stale_rounds >= 8:  # feed exhausted (or nothing new loaded)
                    break
            else:
                stale_rounds = 0
            last_size = len(collected)
            if visible:
                try:
                    # Trusted wheel input over the visible feed is the scroll the paginating
                    # review list actually reacts to: synthetic scrollTop writes reach the
                    # bottom but never fetch the next batch (and the old feed_selector
                    # fallback marked such a no-op scroll as "moved", skipping real input).
                    pos = await _evaluate(page, _WHEEL_TARGET_JS)
                    if pos is not None:
                        await page.mouse.move(pos["x"], pos["y"])
                        at_bottom = pos.get("st", 0) >= pos.get("max", 0) - 8
                        if at_bottom:
                            # At the feed's end sentinel: Google lazy-loads the next batch only
                            # after the list *sits* at its bottom, so nudge gently and dwell —
                            # spinning big wheels past the sentinel made stale detection trip
                            # before the load ever happened.
                            await page.mouse.wheel(0, random.randint(180, 420))
                            await page.wait_for_timeout(1_800)
                        else:
                            await page.mouse.wheel(0, random.randint(700, 1_200))
                    else:
                        # No scrollable container found (pane variants) — fall back to the
                        # synthetic container scroll, then to a DOM wheel + CDP wheel.
                        await _evaluate(page, _SCROLL_FEED_JS)
                        if feed_selector:
                            with contextlib.suppress(PlaywrightError):
                                await page.eval_on_selector(
                                    feed_selector,
                                    "el => { el.scrollTop += Math.floor(el.clientHeight * 0.85); }",
                                )
                        await _evaluate(page, _WHEEL_JS)
                        # bounding_box() waits the full default timeout when nothing matches,
                        # so only look for a card to point at when cards exist.
                        if await self._count_cards(page):
                            last = page.locator("div[data-review-id]").last
                            box = await last.bounding_box()
                            if box is not None:
                                await page.mouse.move(
                                    box["x"] + box["width"] / 2, box["y"] + box["height"] - 40
                                )
                        await page.mouse.wheel(0, random.randint(900, 1_500))
                except PlaywrightError:
                    with contextlib.suppress(PlaywrightError):
                        await page.mouse.wheel(0, 1_200)
            # With nothing rendered there is no feed to scroll: just wait for hydration
            # instead of burning timeouts on ghost scroll work every round.
            await page.wait_for_timeout(random.randint(500, 950))

        # Final expand + harvest: cards that only became expandable after hydration still have
        # their "More" control on screen at the end of the scroll loop.
        with contextlib.suppress(PlaywrightError):
            await _evaluate(page, _EXPAND_MORE_JS)
            await page.wait_for_timeout(250)
            raw = await page.eval_on_selector_all("div[data-review-id]", _EXTRACT_CARD_JS)
            for item in raw:
                rid = (item.get("id") or "").strip()
                if not rid:
                    rid = _stable_anon_review_id(
                        item.get("author") or "", item.get("text") or "", item.get("when")
                    )
                prev = collected.get(rid)
                if prev is None or len((item.get("text") or "").strip()) > len(
                    (prev.get("text") or "").strip()
                ):
                    collected[rid] = item

        return [
            ReviewData(
                google_review_id=rid,
                author=(item.get("author") or "").strip(),
                rating=_first_float(item.get("stars")) or 0.0,
                text=(item.get("text") or "").strip(),
                review_time=parse_when(item.get("when")),
            )
            for rid, item in list(collected.items())[:max_reviews]
        ]

    @staticmethod
    def _boq_to_review(rv: dict) -> ReviewData | None:  # type: ignore[type-arg]
        """One RPC review → ``ReviewData`` (RPC bodies are mini-HTML, timestamps are epoch ints)."""
        text = _clean_boq_text(rv.get("text"))
        author = (rv.get("author") or "").strip()
        if not text and not author:
            return None
        try:
            rating = float(rv.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        review_id = (rv.get("id") or "").strip() or _stable_anon_review_id(
            author, text, rv.get("published")
        )
        return ReviewData(
            google_review_id=review_id,
            author=author,
            rating=rating if 0 <= rating <= 5 else 0.0,
            text=text,
            review_time=_parse_boq_datetime(rv.get("published")),
        )

    async def _collect_reviews_via_boq(
        self, page: Page, feature_id: str, target: int | None = None
    ) -> list[ReviewData]:
        """Fetch the complete review list through Google's ``GetLocalBoqProxy`` RPC.

        The RPC answers 10 reviews per call plus a continuation token and is *not* subject to the
        preview cap the rendered feed hits (live: 39 of 39 reviews here vs 5 through scrolling).
        Orderings 1 (most relevant) and 2 (newest) are both walked and merged — Google truncates
        each ordering on large listings and the union approaches the real total.
        """
        want = _want_count(self.settings.crawler_max_reviews, target)
        # +3 slack so a place whose total is an exact multiple of the page size still reads its
        # final empty page and stops on the missing token instead of on the loop bound.
        max_pages = max(1, -(-want // 10)) + 3
        collected: dict[str, ReviewData] = {}
        for sort_order in (1, 2):
            if len(collected) >= want:
                break
            token = ""
            for _ in range(max_pages):
                payload = _boq_payload(feature_id, sort_order, token)
                res = await _evaluate(
                    page, _BOQ_FETCH_JS, [_BOQ_ENDPOINT, payload], timeout_s=20.0
                )
                if not isinstance(res, dict) or not res.get("ok"):
                    log.debug("boq page failed (sort=%s): %s", sort_order, str(res)[:160])
                    break
                batch: list[dict] = res.get("reviews") or []  # type: ignore[type-arg]
                for raw in batch:
                    row = self._boq_to_review(raw)
                    if row is None:
                        continue
                    prev = collected.get(row.google_review_id)
                    if prev is None or len(row.text) > len(prev.text):
                        collected[row.google_review_id] = row
                token = res.get("token") or ""
                log.debug(
                    "boq sort=%s page=+%d unique=%d token=%s",
                    sort_order,
                    len(batch),
                    len(collected),
                    bool(token),
                )
                if not token or not batch or len(collected) >= want:
                    break
                await page.wait_for_timeout(random.randint(250, 650))
        reviews = list(collected.values())[: self.settings.crawler_max_reviews]
        log.info("review RPC returned %d reviews for %s", len(reviews), feature_id)
        return reviews

    async def _find_review_feed(self, page: Page) -> str | None:
        for selector in (
            'div[aria-label*="Reviews"]',
            'div[aria-label*="lasan"]',  # id-ID "…ulasan" / "Ulasan"
            "div.m6QEbd",
            "div.m6QErb",  # newer pane feed variant (observed on UOB Setiabudi)
            'div[role="main"]',
        ):
            try:
                if await page.locator(f"{selector} div[data-review-id]").count() > 0:
                    return selector
            except PlaywrightError:
                continue
        return None

    async def _read_summary(self, page: Page) -> dict | None:  # type: ignore[type-arg]
        """Capture the overview rating block (may be unmounted after switching tabs)."""
        try:
            return await page.eval_on_selector(
                "div.F7nice",
                """el => ({
                    rating: (el.querySelector('span') || {}).textContent || '',
                    count: ((el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '')).trim(),
                })""",
            )
        except PlaywrightError:
            return None

    async def _read_place_details(self, page: Page) -> dict[str, str]:  # type: ignore[type-arg]
        """Address / phone / website / category / hours from the place overview.

        Best-effort: Maps DOM varies by locale and listing completeness, so every field is
        optional and missing keys stay empty.
        """
        try:
            data = await _evaluate(page, """() => {
                    const text = (sel) => {
                        const n = document.querySelector(sel);
                        return n ? (n.textContent || '').trim() : '';
                    };
                    const attr = (sel, name) => {
                        const n = document.querySelector(sel);
                        return n ? (n.getAttribute(name) || '').trim() : '';
                    };
                    const address =
                        text('button[data-item-id="address"] .Io6YTe') ||
                        text('button[data-item-id="address"]') ||
                        text('div[data-item-id="address"] .Io6YTe') ||
                        text('div[data-item-id="address"]');
                    const phoneBtn = document.querySelector(
                        'button[data-item-id^="phone:tel:"], button[data-item-id^="phone"], ' +
                        'div[data-item-id^="phone:tel:"], div[data-item-id^="phone"]'
                    );
                    let phone = phoneBtn ? (phoneBtn.getAttribute('aria-label') || '') : '';
                    if (!phone && phoneBtn) phone = phoneBtn.textContent || '';
                    phone = phone.replace(/^.*?(?:phone|telepon|telp)\\s*:?\\s*/i, '').trim();
                    const websiteA = document.querySelector('a[data-item-id="authority"]');
                    const website = websiteA ? (websiteA.getAttribute('href') || '').trim() : '';
                    const category =
                        text('button[jsaction*="category"] .DkEaL') ||
                        text('button[jsaction*="category"]') ||
                        text('span.DkEaL') ||
                        text('button.DkEaL');
                    const hours =
                        attr('div[data-item-id="oh"]', 'aria-label') ||
                        text('div[data-item-id="oh"] table') ||
                        text('table.eK4R0e') ||
                        text('div[data-item-id="oh"]');
                    return {
                        address: address || '',
                        phone: phone || '',
                        website: website || '',
                        category: category || '',
                        opening_hours: hours || '',
                    };
                }"""
            )
        except PlaywrightError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            "address": _strip_icon_glyphs(str(data.get("address") or "")),
            "phone": _strip_icon_glyphs(str(data.get("phone") or "")),
            "website": str(data.get("website") or "").strip(),
            "category": _strip_icon_glyphs(str(data.get("category") or "")),
            "opening_hours": _clean_hours(str(data.get("opening_hours") or "")),
        }

    @staticmethod
    def _summarize(data: dict | None, reviews: list[ReviewData]) -> tuple[float, int]:  # type: ignore[type-arg]
        avg = _first_float(data.get("rating")) if data else None
        if avg is not None and avg > 5:  # mis-parse guard (e.g. a rating read as "39")
            avg = None
        count = _parse_count(data.get("count")) if data else None
        if avg is None and reviews:
            rated = [r.rating for r in reviews if 0 < r.rating <= 5]
            avg = sum(rated) / len(rated) if rated else 0.0
        count = len(reviews) if count is None else max(count, len(reviews))
        return round(avg or 0.0, 2), int(count)


async def _self_check(url: str) -> None:  # pragma: no cover - manual helper
    crawler = GoogleMapsCrawler()
    try:
        result = await crawler.scrape(url)
        print(f"avg={result.avg_rating} count={result.review_count} reviews={len(result.reviews)}")  # noqa: T201
    finally:
        await crawler.close()


if __name__ == "__main__":  # pragma: no cover
    import sys

    asyncio.run(_self_check(sys.argv[1]))

