"use client";

import { useState } from "react";

import type { Business, BusinessUpdate } from "@/lib/api";
import { EMPTY_VALUE, fmtDate } from "@/lib/api";
import { downloadCsv, reportName } from "@/lib/export";
import BusinessDetailModal from "@/components/BusinessDetailModal";
import BusinessEditModal from "@/components/BusinessEditModal";
import { DownloadIcon, EditIcon, PlayIcon, StarIcon, TrashIcon } from "@/components/icons";

export default function BusinessTable({
  businesses,
  busyId,
  onEnqueue,
  onEnqueueAll,
  onDelete,
  onUpdate,
}: {
  businesses: Business[];
  busyId: number | null;
  onEnqueue: (id: number) => void;
  onEnqueueAll: () => void;
  onDelete: (id: number) => void;
  /** Patch the name and/or the Maps link; resolves once the refreshed list has arrived. */
  onUpdate: (id: number, patch: BusinessUpdate) => Promise<void>;
}) {
  // Which row is open in the edit dialog / the detail dialog (both are modal overlays).
  const [editing, setEditing] = useState<Business | null>(null);
  const [detail, setDetail] = useState<Business | null>(null);

  /** Location and scraper report for every tracked listing. Dates stay in raw
   *  ISO so spreadsheets sort them; empty cells mean "not collected yet". */
  const exportCsv = () => {
    downloadCsv(
      reportName("businesses"),
      [
        "Name",
        "Kind",
        "Category",
        "Address",
        "Phone",
        "Website",
        "Avg rating",
        "Reviews",
        "Status",
        "Consecutive blocks",
        "Last scraped",
        "Opening hours",
        "Maps URL",
        "Created",
        "Updated",
      ],
      businesses.map((b) => [
        b.name,
        b.kind,
        b.category,
        b.address,
        b.phone,
        b.website,
        b.avg_rating !== null ? b.avg_rating.toFixed(1) : null,
        b.review_count,
        b.status,
        b.consecutive_blocks,
        b.last_scraped_at,
        b.opening_hours,
        b.maps_url,
        b.created_at,
        b.updated_at,
      ]),
    );
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Businesses ({businesses.length})</h2>
        <div className="topbar-actions">
          <button
            className="ghost"
            onClick={exportCsv}
            disabled={businesses.length === 0}
            title="Download every business detail as CSV (rating, reviews, address, hours)"
          >
            <DownloadIcon /> Export CSV
          </button>
          <button className="primary" onClick={onEnqueueAll} disabled={busyId !== null}>
            <PlayIcon /> Run All Now
          </button>
        </div>
      </div>
      <p className="section-hint" style={{ margin: `0 0 var(--space-2)` }}>
        Click any row for details (address, phone, hours…).
      </p>
      {businesses.length === 0 ? (
        <p className="empty">No businesses yet. Add one above.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Rating</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Scraped</th>
                <th className="num">Blocks</th>
                <th className="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              {businesses.map((b) => (
                <tr
                  key={b.id}
                  className="clickable-row"
                  onClick={() => setDetail(b)}
                  title="View business details"
                >
                  <td>
                    <div className="name-cell">
                      <span className="linklike">{b.name}</span>
                      <a
                        className="url-link"
                        href={b.maps_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {b.maps_url}
                      </a>
                    </div>
                  </td>
                  <td className="rating-cell">
                    {b.avg_rating !== null ? (
                      <span title={`${b.avg_rating} / 5`}>
                        <span className="review-stars">
                          <StarIcon />
                        </span>{" "}
                        {b.avg_rating.toFixed(1)}
                        <span className="muted">
                          {b.review_count ?? 0} review
                          {(b.review_count ?? 0) === 1 ? "" : "s"}
                        </span>
                      </span>
                    ) : (
                      <span className="muted">{EMPTY_VALUE}</span>
                    )}
                  </td>
                  <td>
                    <span className={`kind-badge ${b.kind}`}>{b.kind}</span>
                  </td>
                  <td>
                    <span className={`badge ${b.status}`}>{b.status}</span>
                    {b.status === "backoff" && b.consecutive_blocks > 0 && (
                      <div className="muted">block #{b.consecutive_blocks}</div>
                    )}
                    {b.status === "parked" && b.parked_until && (
                      <div className="muted">until {fmtDate(b.parked_until)}</div>
                    )}
                  </td>
                  <td className="date-cell">{fmtDate(b.last_scraped_at)}</td>
                  <td className="num">{b.consecutive_blocks}</td>
                  <td>
                    <div className="actions" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="small row-action"
                        disabled={busyId !== null || b.status === "parked"}
                        title={b.status === "parked" ? "Parked: wait until the park window ends" : "Queue a scrape now"}
                        aria-label={`Run ${b.name} now`}
                        onClick={() => onEnqueue(b.id)}
                      >
                        <PlayIcon />
                      </button>
                      <button
                        className="ghost small row-action"
                        disabled={busyId !== null}
                        title="Edit name and Google Maps URL"
                        aria-label={`Edit ${b.name}`}
                        onClick={() => {
                          setDetail(null);
                          setEditing(b);
                        }}
                      >
                        <EditIcon />
                      </button>
                      <button
                        className="small danger row-action"
                        disabled={busyId !== null}
                        title="Delete this listing and all its data"
                        aria-label={`Delete ${b.name}`}
                        onClick={() => onDelete(b.id)}
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detail && (
        <BusinessDetailModal
          business={businesses.find((x) => x.id === detail.id) ?? detail}
          onClose={() => setDetail(null)}
        />
      )}
      {editing && (
        <BusinessEditModal
          business={businesses.find((x) => x.id === editing.id) ?? editing}
          busy={busyId === editing.id}
          onClose={() => setEditing(null)}
          onSave={async (patch) => {
            await onUpdate(editing.id, patch);
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}
