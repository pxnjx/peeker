"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Business, Review } from "@/lib/api";
import { REVIEW_PAGE_SIZE, api, fmtDate } from "@/lib/api";
import { downloadCsv, reportName } from "@/lib/export";
import { CloseIcon, DownloadIcon, StarIcon, StarOutlineIcon } from "@/components/icons";

/** Cap on rows painted at once. The review cards render eagerly. */
const MAX_ROWS = 300;

/** Five SVG stars; the rounded rating decides how many are filled. */
function Stars({ rating }: { rating: number }) {
  const filled = Math.round(Math.max(0, Math.min(5, rating)));
  return (
    <>
      {Array.from({ length: 5 }, (_, i) =>
        i < filled ? <StarIcon key={i} /> : <StarOutlineIcon key={i} />,
      )}
    </>
  );
}

const RATING_FILTERS = [
  { value: "all", label: "All" },
  { value: "5", label: "5" },
  { value: "4", label: "4" },
  { value: "3", label: "3" },
  { value: "2", label: "2" },
  { value: "1", label: "1" },
] as const;

type RatingFilter = (typeof RATING_FILTERS)[number]["value"];

export default function ReviewsViewer({ businesses }: { businesses: Business[] }) {
  const [selected, setSelected] = useState<number | "all" | null>("all"); // default: newest across all businesses
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>("all");
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Requests get a sequence number: switching businesses quickly fires several fetches and
  // they can resolve out of order, so a late reply for the previous selection must be dropped.
  const requestId = useRef(0);

  const load = useCallback(async (target: number | "all") => {
    const reqId = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const list =
        target === "all"
          ? await api.reviewsAll({ limit: REVIEW_PAGE_SIZE })
          : await api.reviews(target, REVIEW_PAGE_SIZE);
      if (reqId !== requestId.current) return;
      setReviews(list);
    } catch (err) {
      if (reqId !== requestId.current) return;
      setError(err instanceof Error ? err.message : String(err));
      setReviews(null);
    } finally {
      if (reqId === requestId.current) setLoading(false);
    }
  }, []);

  // Drop a selection that points at a deleted business.
  useEffect(() => {
    if (selected === null || selected === "all") return;
    if (businesses.some((b) => b.id === selected)) return;
    setSelected("all");
  }, [selected, businesses]);

  useEffect(() => {
    if (selected === null) return;
    load(selected);
  }, [selected, load]);

  const filtered = useMemo(() => {
    if (!reviews) return [];
    if (ratingFilter === "all") return reviews;
    const want = Number(ratingFilter);
    return reviews.filter((r) => Math.round(r.rating) === want);
  }, [reviews, ratingFilter]);

  const visible = filtered.slice(0, MAX_ROWS);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: reviews?.length ?? 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0 };
    for (const r of reviews ?? []) {
      const k = String(Math.round(Math.max(1, Math.min(5, r.rating))));
      c[k] = (c[k] ?? 0) + 1;
    }
    return c;
  }, [reviews]);

  /** Report of the current view: the business selection and rating filter apply. */
  const exportCsv = () => {
    downloadCsv(
      reportName("reviews"),
      [
        "Business",
        "Kind",
        "Author",
        "Rating",
        "Comment",
        "Has comment",
        "Review date",
        "First seen",
      ],
      filtered.map((r) => [
        r.business_name,
        businesses.find((b) => b.id === r.business_id)?.kind ?? null,
        r.author || "Anonymous",
        r.rating,
        r.text,
        r.text ? "yes" : "no",
        r.review_time ?? r.first_seen_at,
        r.first_seen_at,
      ]),
    );
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Reviews / Comments</h2>
        <div style={{ flex: 1, minWidth: 240 }}>
          <select
            aria-label="Select business"
            value={selected === null ? "" : String(selected)}
            onChange={(e) => {
              const v = e.target.value;
              setSelected(v === "" ? null : v === "all" ? "all" : Number(v));
            }}
          >
            <option value="">Select a business</option>
            <option value="all">All businesses</option>
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <button
          className="ghost"
          onClick={exportCsv}
          disabled={filtered.length === 0}
          title="Download the reviews in this view as CSV (rating, comment, dates)"
        >
          <DownloadIcon /> Export CSV
        </button>
      </div>

      <div className="review-filters" role="group" aria-label="Filter by rating">
        {RATING_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`filter-chip${ratingFilter === f.value ? " active" : ""}`}
            onClick={() => setRatingFilter(f.value)}
            aria-pressed={ratingFilter === f.value}
          >
            {f.value === "all" ? (
              f.label
            ) : (
              <>
                {f.label}
                <StarIcon />
              </>
            )}
            <span className="filter-count">{counts[f.value] ?? 0}</span>
          </button>
        ))}
      </div>

      <div style={{ marginTop: "var(--space-3)" }}>
        {selected === null && (
          <p className="empty">
            Select a business to see its Google Maps reviews/comments.
          </p>
        )}
        {selected !== null && loading && <p className="empty">Loading…</p>}
        {selected !== null && !loading && error && (
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
        {selected !== null && !loading && !error && reviews?.length === 0 && (
          <p className="empty">
            No reviews stored yet. The business may have 0 reviews or its
            <code> maps_url</code> still points to a placeholder link.
          </p>
        )}
        {selected !== null &&
          !loading &&
          !error &&
          reviews !== null &&
          reviews.length > 0 &&
          filtered.length === 0 && (
            <p className="empty">No reviews match this rating filter.</p>
          )}
        {selected !== null &&
          !loading &&
          !error &&
          filtered.length > 0 && (
            <div className="reviews-list">
              {visible.map((r) => (
                <div className="review-card" key={r.id}>
                  <div className="review-head">
                    <span className="review-author">{r.author || "Anonymous"}</span>
                    {selected === "all" && (
                      <span className="kind-tag">{r.business_name}</span>
                    )}
                    <span
                      className="review-stars"
                      role="img"
                      aria-label={`${r.rating} out of 5 stars`}
                    >
                      <Stars rating={r.rating} />
                    </span>
                    <span className="muted">{r.rating.toFixed(1)}</span>
                    <span className="muted">
                      {fmtDate(r.review_time ?? r.first_seen_at)}
                    </span>
                  </div>
                  {r.text ? (
                    <p className="review-text">{r.text}</p>
                  ) : (
                    <p className="review-text muted">(no comment, rating only)</p>
                  )}
                </div>
              ))}
            </div>
          )}
        {filtered.length > visible.length && (
          <p className="empty">
            + {filtered.length - visible.length} more matching reviews hidden. Only the newest{" "}
            {MAX_ROWS} render.
          </p>
        )}
      </div>
    </div>
  );
}
