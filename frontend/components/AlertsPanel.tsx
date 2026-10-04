"use client";

import type { Alert, Business } from "@/lib/api";
import { fmtDate } from "@/lib/api";
import { CheckIcon } from "@/components/icons";

export default function AlertsPanel({
  alerts,
  businesses,
  onSeen,
  onSeenAll,
  busyAll = false,
  openTotal,
  total,
}: {
  alerts: Alert[];
  businesses: Business[];
  onSeen: (id: number) => void;
  /** Bulk dismiss: one request for every open alert. */
  onSeenAll: () => void;
  /** Bulk request in flight (disables the button so it can't be double-fired). */
  busyAll?: boolean;
  /** Total open alerts across the app (when only a subset is shown). */
  openTotal?: number;
  /** Total alerts that exist (when only a subset is shown). */
  total?: number;
}) {
  const nameOf = (id: number) =>
    businesses.find((b) => b.id === id)?.name ?? `#${id}`;
  const open = openTotal ?? alerts.filter((a) => !a.seen).length;
  const shown = alerts.length;
  const exists = total ?? shown;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Alerts ({open} open)</h2>
        <div className="topbar-actions">
          <span className="muted">
            {exists > shown ? `${shown} of ${exists} shown` : `${shown} shown`}
          </span>
          {open > 0 && (
            <button
              className="small ghost"
              onClick={onSeenAll}
              disabled={busyAll}
              title="Mark every open alert as seen in one request"
            >
              {busyAll ? "Marking…" : <><CheckIcon /> Mark all seen</>}
            </button>
          )}
        </div>
      </div>
      {alerts.length === 0 ? (
        <p className="empty">No alerts yet. Rating drops and review bursts show up here.</p>
      ) : (
        <div className="scroll-list">
          {alerts.map((a) => (
            <div className={`alert-item${a.seen ? " seen" : ""}`} key={a.id}>
              <div className="msg">
                <div>{a.message}</div>
                <div className="meta">
                  {nameOf(a.business_id)} ({a.kind}) · {fmtDate(a.created_at)}
                  {a.urgent ? <span className="urgency">urgent</span> : null}
                </div>
              </div>
              {!a.seen && (
                <button className="small ghost" onClick={() => onSeen(a.id)}>
                  Mark seen
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
