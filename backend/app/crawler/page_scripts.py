"""Browser-side JS snippets for the Maps crawler.

Kept out of the crawler class so the page-touching logic stays readable and
these strings can be reviewed (or replaced) independently.
"""

# Reviews only paginate below the visible cards: poke the feed, then scroll. A DOM wheel
# event works from any cursor position; the CDP wheel needs the cursor on the pane.
_WHEEL_JS = """() => {
    document.querySelectorAll('div[data-review-id]').forEach((el, i, arr) => {
        if (i === arr.length - 1) {
            el.dispatchEvent(new WheelEvent('wheel',
                { bubbles: true, cancelable: true, deltaY: 1200, clientX: 300, clientY: 700 }));
        }
    });
    return true;
}"""
# Scroll to the very bottom of the deepest scrollable container that holds review cards: the Maps
# feed paginates when its end sentinel scrolls into view; screen-sized hops can hover above it.
_SCROLL_FEED_JS = """() => {
    const nodes = document.querySelectorAll('div[data-review-id]');
    if (!nodes.length) { window.scrollBy(0, 900); return true; }
    let best = null;
    for (const n of nodes) {
        let e = n;
        while (e && e !== document.body) {
            const st = getComputedStyle(e);
            if ((st.overflowY === 'auto' || st.overflowY === 'scroll')
                && e.scrollHeight > e.clientHeight + 40) {
                if (!best || e.scrollHeight > best.scrollHeight) best = e;
            }
            e = e.parentElement;
        }
    }
    if (!best) { window.scrollBy(0, 900); return true; }
    const before = best.scrollTop + best.clientHeight;
    best.scrollTop = best.scrollHeight;
    return best.scrollTop + best.clientHeight > before;
}"""

# Extract one rendered review card into the plain dict the crawler consumes. Used both in
# the scroll loop and at the final harvest, so this selector list lives once here.
_EXTRACT_CARD_JS = """nodes => nodes.map(el => {
    const pick = (...sels) => {
        for (const s of sels) {
            const n = el.querySelector(s);
            if (n && (n.textContent || '').trim()) return n;
        }
        return null;
    };
    // Prefer the expanded body; fall back to the preview node.
    const body =
        pick('.MyEned .review-full-text', '.MyEned', '.wiI7pd',
             '[data-expandable-section] .review-full-text',
             '[data-expandable-section]', '.OA1nbd .review-full-text', '.OA1nbd');
    let text = body ? (body.textContent || '') : '';
    // Strip the expander's own label if it leaked into the container text.
    text = text.replace(
        /\\s*(More|Selengkapnya|See more|Lihat selengkapnya)\\s*$/i, ''
    ).trim();
    return {
        id: el.getAttribute('data-review-id') || '',
        author: (el.querySelector(
                    '.d4r55, .d6SCIc, .GHTaQb, .WNxzHc .qLhwUc') || {}).textContent
                || el.getAttribute('aria-label') || '',
        text,
        when: (el.querySelector('.rsqaWe, .DU9Pgb span[role="datetime"]') || {})
                .textContent || '',
        stars: (el.querySelector(
                    'span[role="img"][aria-label*="star" i], ' +
                    'span[role="img"][aria-label*="bintang" i]') || {})
                .getAttribute?.('aria-label')
                || (el.querySelector('.kvMYJc') || {}).textContent || ''
    };
})"""

_TABS_JS = """() => {
    if (location.pathname.includes('/reviews')) return 'reviews';
    const t = document.querySelector('[role="tab"][aria-selected="true"]');
    return t ? (t.textContent || '').trim() : '';
}"""

# Google collapses long bodies behind "More" / "Selengkapnya". The truncated preview is what
# `.wiI7pd`/`.MyEned` textContent holds (often ending in "…"); the full body only appears after
# the card-local expander is clicked. Do this per card before harvesting text.
_EXPAND_MORE_JS = """() => {
    // Exact / near-exact labels only — "2 more years" must not match.
    const exact = new Set([
        'more', 'selengkapnya', 'see more', 'lihat selengkapnya',
        'lihat lainnya', 'read more', 'tampilkan lainnya', 'more...'
    ]);
    let clicked = 0;
    document.querySelectorAll('div[data-review-id]').forEach((el) => {
        el.querySelectorAll('button, [role="button"], span[role="button"]').forEach((btn) => {
            const t = ((btn.textContent || '') + ' ' + (btn.getAttribute('aria-label') || ''))
                .trim().toLowerCase().replace(/\\s+/g, ' ');
            if (!t || !exact.has(t)) return;
            try { btn.click(); clicked += 1; } catch (e) {}
        });
    });
    return clicked;
}"""

# Scroll the last visible card (the list's end sentinel) into view: Google renders the overview
# preview as a pinned strip, and the real paginating list only expands once that sentinel moves.
_END_SENTINEL_JS = """() => {
    const poke = () => {
        const nodes = document.querySelectorAll('div[data-review-id]');
        const last = nodes[nodes.length - 1];
        if (last) last.scrollIntoView({ block: 'end' });
        const y = document.querySelector('div[role="main"]');
        if (y) { y.scrollTop = y.scrollHeight; }
        return nodes.length;
    };
    const before = poke();
    return before;
}"""

# Viewport coords of the largest *visible* scrollable container holding review cards.
# A trusted wheel (page.mouse.wheel) delivered here is what makes the review-list view
# fetch its next batch: live probes showed synthetic scrollTop writes reach the bottom
# but the feed never paginates (tab pane stuck at 5/39; the same feed grew only after
# real wheel input at these coordinates).
_WHEEL_TARGET_JS = """() => {
    let best = null;
    document.querySelectorAll('div[data-review-id]').forEach((n) => {
        let e = n;
        while (e && e !== document.body) {
            const st = getComputedStyle(e);
            if ((st.overflowY === 'auto' || st.overflowY === 'scroll')
                && e.scrollHeight > e.clientHeight + 40) {
                const r = e.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && (!best || e.scrollHeight > best.sh)) {
                    best = { sh: e.scrollHeight,
                             x: Math.min(Math.max(r.x + r.width / 2, 8), window.innerWidth - 8),
                             y: Math.min(Math.max(r.y + r.height - 60, 8), window.innerHeight - 8),
                             st: e.scrollTop,
                             max: e.scrollHeight - e.clientHeight };
                }
            }
            e = e.parentElement;
        }
    });
    return best;
}"""

# Google's own review RPC, called from inside the page so the request is same-origin and carries
# the session cookies. The DOM feed only ever renders a capped preview (live: 5 cards of 39 on the
# UOB Setiabudi listing) while this endpoint returns the whole list, 10 per page, with a token.
_BOQ_ENDPOINT = (
    "https://www.google.com/httpservice/web/PrivateLocalSearchUiDataService/GetLocalBoqProxy"
    "?msc=gwsrpc&reqpld="
)

# Parse mirrors google-maps-review-scraper/src/boqParser.ts: the review body sits next to the
# "Google" owner marker of the reply chain, so locate that marker instead of guessing an index.
_BOQ_FETCH_JS = """async ([endpoint, payloadStr]) => {
    const url = endpoint + encodeURIComponent(payloadStr);
    const resp = await fetch(url, { credentials: 'include' });
    const text = await resp.text();
    if (!resp.ok) return { ok: false, status: resp.status, head: text.slice(0, 200) };
    const parts = text.split(")]}'");
    const raw = parts.length > 1 ? parts[1] : parts[0];
    let data;
    try {
        data = JSON.parse(raw);
    } catch (e) {
        return { ok: false, status: resp.status, err: String(e), head: text.slice(0, 200) };
    }
    const node = Array.isArray(data) && Array.isArray(data[1]) ? data[1][10] : null;
    if (!node || !Array.isArray(node[2])) return { ok: true, reviews: [], token: '', empty: true };
    const reviews = node[2].map((rv) => {
        const getPath = (arr, path) => path.reduce(
            (acc, i) => (Array.isArray(acc) ? acc[i] : undefined), arr
        );
        let googleIdx = -1;
        for (let i = rv.length - 1; i >= 0; i--) {
            if (Array.isArray(rv[i]) && rv[i][0] === 'Google') { googleIdx = i; break; }
        }
        let full = null, short = null, lang = null;
        if (googleIdx > 0) {
            let qaIdx = -1;
            for (let i = googleIdx - 1; i >= 6; i--) {
                if (typeof getPath(rv[i], [0, 0, 0]) === 'string') { qaIdx = i; break; }
            }
            if (qaIdx !== -1) {
                if (typeof rv[qaIdx - 2] === 'string') short = rv[qaIdx - 2];
                if (typeof rv[qaIdx - 3] === 'string') full = rv[qaIdx - 3];
                if (typeof rv[qaIdx - 4] === 'string' && rv[qaIdx - 4].length === 2) {
                    lang = rv[qaIdx - 4];
                }
            }
        }
        if (!full && !short) {
            const stop = googleIdx > 0 ? googleIdx : rv.length;
            for (let i = 6; i < stop; i++) {
                const v = rv[i];
                if (typeof v === 'string' && v.length > 5 && !v.startsWith('http')) {
                    if (!full) full = v;
                    else if (v !== full && !short) short = v;
                }
            }
        }
        const author = Array.isArray(rv[3]) ? rv[3] : [];
        return {
            id: typeof rv[5] === 'string' ? rv[5] : '',
            rating: typeof rv[1] === 'number' ? rv[1] : 0,
            published: Array.isArray(rv[2]) ? rv[2][2] : null,
            author: typeof author[0] === 'string' ? author[0] : '',
            text: full || short || '',
            lang: lang || '',
        };
    });
    const token = node.length > 6 && typeof node[6] === 'string' ? node[6] : '';
    return { ok: true, reviews, token };
}"""
