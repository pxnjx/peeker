"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Business, Review, Stats } from "@/lib/api";
import { EMPTY_VALUE, api, fmtDate, parseIsoDate } from "@/lib/api";
import { downloadCsv, reportName } from "@/lib/export";
import { CloseIcon, DownloadIcon } from "@/components/icons";

/** One reviews call is capped at ANALYZE_LIMIT rows by the frontend, so this page analyses
 * "the newest 500 stored reviews". Every panel says so in its hint. The backend would allow
 * up to 2000 (REVIEW_LIMIT_MAX), but 500 keeps the poll payload small. */
const ANALYZE_LIMIT = 500;

/** Trend window: this calendar month and the five months before it. */
const TREND_MONTHS = 6;

interface Side {
  listings: number;
  /** review-weighted average of the listing snapshots (null before first scrape) */
  rating: number | null;
  reviews: number;
}

interface BizRow {
  business: Business;
  stored: number;
  comments: number;
  /** stored reviews rounded to 1 or 2 stars */
  low: number;
  lastAt: string | null;
}

export default function AnalyzePanel({
  businesses,
  stats,
}: {
  businesses: Business[];
  stats: Stats | null;
}) {
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  // Sequence number so a late reply can never overwrite a newer fetch.
  useEffect(() => {
    const reqId = ++requestId.current;
    setLoading(true);
    setError(null);
    api
      .reviewsAll({ limit: ANALYZE_LIMIT })
      .then((list) => {
        if (reqId !== requestId.current) return;
        setReviews(list);
      })
      .catch((err) => {
        if (reqId !== requestId.current) return;
        setError(err instanceof Error ? err.message : String(err));
        setReviews(null);
      })
      .finally(() => {
        if (reqId === requestId.current) setLoading(false);
      });
  }, []);

  const summary = useMemo(() => {
    const list = reviews ?? [];
    const withComment = list.filter((r) => r.text.trim() !== "").length;
    const avg = list.length > 0 ? list.reduce((s, r) => s + r.rating, 0) / list.length : null;
    return { total: list.length, withComment, avg };
  }, [reviews]);

  const dist = useMemo(() => {
    const c: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
    for (const r of reviews ?? []) {
      c[Math.max(1, Math.min(5, Math.round(r.rating)))] += 1;
    }
    return c;
  }, [reviews]);

  const sides = useMemo(() => {
    const make = (kind: Business["kind"]): Side => {
      const list = businesses.filter((b) => b.kind === kind);
      let weight = 0;
      let sum = 0;
      let total = 0;
      for (const b of list) {
        total += b.review_count ?? 0;
        if (b.avg_rating === null) continue;
        // Unrated listings carry weight 1 so an empty listing still counts as a listing.
        const w = b.review_count ?? 1;
        sum += b.avg_rating * w;
        weight += w;
      }
      return { listings: list.length, rating: weight > 0 ? sum / weight : null, reviews: total };
    };
    const own = make("own");
    const competitor = make("competitor");
    const gap =
      own.rating !== null && competitor.rating !== null ? own.rating - competitor.rating : null;
    return { own, competitor, gap };
  }, [businesses]);

  const trend = useMemo(() => {
    const now = new Date();
    const months: { key: string; label: string; count: number; avg: number | null }[] = [];
    for (let i = TREND_MONTHS - 1; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      months.push({
        key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
        label: d.toLocaleDateString(undefined, { month: "short", year: "2-digit" }),
        count: 0,
        avg: null,
      });
    }
    const sums: Record<string, { total: number; n: number }> = {};
    for (const r of reviews ?? []) {
      const iso = r.review_time ?? r.first_seen_at;
      const d = parseIsoDate(iso);
      if (!d) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      const bucket = months.find((m) => m.key === key);
      if (!bucket) continue;
      bucket.count += 1;
      sums[key] = sums[key] ?? { total: 0, n: 0 };
      sums[key].total += r.rating;
      sums[key].n += 1;
    }
    for (const m of months) m.avg = sums[m.key] ? sums[m.key].total / sums[m.key].n : null;
    return months;
  }, [reviews]);

  const rows = useMemo<BizRow[]>(() => {
    const sorted = businesses.map((b) => {
      const mine = (reviews ?? []).filter((r) => r.business_id === b.id);
      let lastAt: string | null = null;
      for (const r of mine) {
        const iso = r.review_time ?? r.first_seen_at;
        // ISO 8601 sorts correctly as plain text, so the newest string wins.
        if (lastAt === null || iso > lastAt) lastAt = iso;
      }
      return {
        business: b,
        stored: mine.length,
        comments: mine.filter((r) => r.text.trim() !== "").length,
        low: mine.filter((r) => Math.round(r.rating) <= 2).length,
        lastAt,
      };
    });
    // Own listings first, then by how much data they have.
    sorted.sort((a, b) => {
      if (a.business.kind !== b.business.kind) return a.business.kind === "own" ? -1 : 1;
      return (b.business.review_count ?? 0) - (a.business.review_count ?? 0);
    });
    return sorted;
  }, [businesses, reviews]);

  /** The whole analysis as one CSV: rating, review volume, comments, location. */
  const exportAnalysis = () => {
    downloadCsv(
      reportName("analysis"),
      [
        "Business",
        "Kind",
        "Category",
        "Address",
        "Avg rating",
        "Reviews",
        "Stored",
        "Comments",
        "Comment share %",
        "Low ratings",
        "Last review",
        "Status",
      ],
      rows.map(({ business: b, stored, comments, low, lastAt }) => [
        b.name,
        b.kind,
        b.category,
        b.address,
        b.avg_rating !== null ? b.avg_rating.toFixed(1) : null,
        b.review_count,
        stored,
        comments,
        stored > 0 ? Math.round((comments / stored) * 100) : null,
        low,
        lastAt,
        b.status,
      ]),
    );
  };

  const pct = (part: number, whole: number = summary.total) =>
    whole > 0 ? Math.round((part / whole) * 100) : 0;
  const maxTrend = Math.max(1, ...trend.map((m) => m.count));
  const gapClass =
    sides.gap === null ? "flat" : sides.gap > 0.005 ? "good" : sides.gap < -0.005 ? "bad" : "flat";
  const signed = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
  const fmtSide = (s: Side) => (s.rating !== null ? s.rating.toFixed(2) : EMPTY_VALUE);

  return (
    <>
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <button
            type="button"
            className="banner-dismiss"
            onClick={() => setError(null)}
            aria-label="Dismiss error"
          >
            <CloseIcon />
          </button>
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Avg rating</div>
          <div className="value">{summary.avg !== null ? summary.avg.toFixed(2) : "…"}</div>
          <div className="muted">across {summary.total} stored</div>
        </div>
        <div className="stat-card">
          <div className="label">Stored reviews</div>
          <div className="value">{reviews ? summary.total : "…"}</div>
          <div className="muted">of {stats ? stats.reviews : "…"} total</div>
        </div>
        <div className="stat-card">
          <div className="label">With comment</div>
          <div className="value">{reviews ? `${pct(summary.withComment)}%` : "…"}</div>
          <div className="muted">
            {summary.withComment} of {summary.total} written
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Rating gap</div>
          <div className={`value delta ${gapClass}`}>
            {sides.gap !== null ? signed(sides.gap) : "…"}
          </div>
          <div className="muted">
            yours {fmtSide(sides.own)} vs them {fmtSide(sides.competitor)}
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>Rating distribution</h2>            <span className="section-hint">
              {loading ? "loading…" : `newest ${summary.total} stored`}
            </span>
          </div>
          {[5, 4, 3, 2, 1].map((star) => (
            <div className="bar-row" key={star}>
              <span className="bar-label">
                {star} star{star === 1 ? "" : "s"}
              </span>
              <div className="bar-track">
                {dist[star] > 0 && (
                  <div className="bar-fill" style={{ width: `${Math.max(2, pct(dist[star]))}%` }} />
                )}
              </div>
              <span className="bar-value">
                {dist[star]} · {pct(dist[star])}%
              </span>
            </div>
          ))}
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>Yours vs competitors</h2>
            <span className="section-hint">review-weighted</span>
          </div>
          {/* .table-scroll, not .table-wrap: this table sits flush in its panel
              and has three rows, so the wrapper's frame, 720px floor and sticky
              header are all wrong here. What it does need is the overflow
              guard -- see .table-scroll in dashboard.css. */}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Side</th>
                  <th className="num">Listings</th>
                  <th className="num">Avg rating</th>
                  <th className="num">Reviews</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <span className="kind-badge own">Yours</span>
                  </td>
                  <td className="num">{sides.own.listings}</td>
                  <td className="num">{fmtSide(sides.own)}</td>
                  <td className="num">{sides.own.reviews}</td>
                </tr>
                <tr>
                  <td>
                    <span className="kind-badge competitor">Competitors</span>
                  </td>
                  <td className="num">{sides.competitor.listings}</td>
                  <td className="num">{fmtSide(sides.competitor)}</td>
                  <td className="num">{sides.competitor.reviews}</td>
                </tr>
                <tr>
                  <td>
                    <strong>Gap</strong>
                  </td>
                  <td className="num muted">
                    {signed(sides.own.listings - sides.competitor.listings)}
                  </td>
                  <td className={`num delta ${gapClass}`}>
                    {sides.gap !== null ? signed(sides.gap) : EMPTY_VALUE}
                  </td>
                  <td className="num">{signed(sides.own.reviews - sides.competitor.reviews)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Review trend</h2>
          <span className="section-hint">reviews per month · avg rating after the dot</span>
        </div>
        {trend.map((m) => (
          <div className="bar-row" key={m.key}>
            <span className="bar-label">{m.label}</span>
            <div className="bar-track">
              {m.count > 0 && (
                <div
                  className="bar-fill"
                  style={{ width: `${Math.max(2, Math.round((m.count / maxTrend) * 100))}%` }}
                />
              )}
            </div>
            <span className="bar-value">
              {m.count} · {m.avg !== null ? m.avg.toFixed(1) : EMPTY_VALUE}
            </span>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Business comparison ({rows.length})</h2>
          <button
            className="ghost"
            onClick={exportAnalysis}
            disabled={rows.length === 0}
            title="Download this analysis as CSV (rating, comments, location details)"
          >
            <DownloadIcon /> Export CSV
          </button>
        </div>
        {rows.length === 0 ? (
          <p className="empty">Add a business above; the analysis fills in after the first scrape.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Business</th>
                  <th>Kind</th>
                  <th className="num">Rating</th>
                  <th className="num">Reviews</th>
                  <th className="num">Stored</th>
                  <th className="num">Comments</th>
                  <th className="num">Low</th>
                  <th>Last review</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ business: b, stored, comments, low, lastAt }) => (
                  <tr key={b.id}>
                    <td>
                      <strong>{b.name}</strong>
                      <div className="muted">{b.category ?? EMPTY_VALUE}</div>
                    </td>
                    <td>
                      <span className={`kind-badge ${b.kind}`}>{b.kind}</span>
                    </td>
                    <td className="num">
                      {b.avg_rating !== null ? b.avg_rating.toFixed(1) : EMPTY_VALUE}
                    </td>
                    <td className="num">{b.review_count ?? 0}</td>
                    <td className="num">{stored}</td>
                    <td className="num">
                      {comments}
                      <span className="muted">
                        {stored > 0 ? ` (${pct(comments, stored)}%)` : ""}
                      </span>
                    </td>
                    <td className="num">{low}</td>
                    <td className="date-cell">{lastAt ? fmtDate(lastAt) : EMPTY_VALUE}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
