"use client";

import type { Business } from "@/lib/api";
import { EMPTY_VALUE, fmtDate } from "@/lib/api";
import { useEscape } from "@/lib/useEscape";
import { ArrowRightIcon, CloseIcon, StarIcon } from "@/components/icons";

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="detail-row">
      <div className="detail-label">{label}</div>
      <div className="detail-value">{children}</div>
    </div>
  );
}

export default function BusinessDetailModal({
  business,
  onClose,
}: {
  business: Business;
  onClose: () => void;
}) {
  useEscape(onClose);

  const hours = (business.opening_hours || "").trim();

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="biz-detail-title"
      >
        <div className="modal-head">
          <div>
            <h3 id="biz-detail-title">{business.name}</h3>
            <div className="modal-sub">
              <span className={`kind-badge ${business.kind}`}>{business.kind}</span>
              <span className={`badge ${business.status}`}>{business.status}</span>
            </div>
          </div>
          <button
            type="button"
            className="banner-dismiss"
            onClick={onClose}
            aria-label="Close details"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="modal-body">
          <DetailRow label="Rating">
            {business.avg_rating !== null ? (
              <span>
                <span className="review-stars">
                  <StarIcon />
                </span>{" "}
                {business.avg_rating.toFixed(1)}
                <span className="muted">
                  {" · "}
                  {business.review_count ?? 0} review
                  {(business.review_count ?? 0) === 1 ? "" : "s"}
                </span>
              </span>
            ) : (
              <span className="muted">Not scraped yet</span>
            )}
          </DetailRow>

          <DetailRow label="Category">
            {business.category || <span className="muted">{EMPTY_VALUE}</span>}
          </DetailRow>

          <DetailRow label="Address">
            {business.address || <span className="muted">{EMPTY_VALUE}</span>}
          </DetailRow>

          <DetailRow label="Phone">
            {business.phone ? (
              <a href={`tel:${business.phone.replace(/\s+/g, "")}`}>{business.phone}</a>
            ) : (
              <span className="muted">{EMPTY_VALUE}</span>
            )}
          </DetailRow>

          <DetailRow label="Website">
            {business.website ? (
              <a
                className="url-link"
                href={business.website}
                target="_blank"
                rel="noreferrer"
              >
                {business.website}
              </a>
            ) : (
              <span className="muted">{EMPTY_VALUE}</span>
            )}
          </DetailRow>

          <DetailRow label="Hours">
            {hours ? (
              <pre className="hours-block">{hours}</pre>
            ) : (
              <span className="muted">{EMPTY_VALUE}</span>
            )}
          </DetailRow>

          <DetailRow label="Google Maps">
            <a
              className="url-link"
              href={business.maps_url}
              target="_blank"
              rel="noreferrer"
            >
              {business.maps_url}
            </a>
          </DetailRow>

          <DetailRow label="Next due">{fmtDate(business.next_due_at)}</DetailRow>
          <DetailRow label="Blocks">
            {business.consecutive_blocks}
            {business.status === "backoff" && business.consecutive_blocks > 0
              ? " (in backoff)"
              : ""}
          </DetailRow>
          {business.status === "parked" && business.parked_until && (
            <DetailRow label="Parked until">{fmtDate(business.parked_until)}</DetailRow>
          )}
          <DetailRow label="Tracked since">{fmtDate(business.created_at)}</DetailRow>
        </div>

        <div className="modal-foot">
          <button type="button" className="ghost" onClick={onClose}>
            Close
          </button>
          <a className="btn-link" href={business.maps_url} target="_blank" rel="noreferrer">
            Open in Google Maps <ArrowRightIcon />
          </a>
        </div>
      </div>
    </div>
  );
}
