"use client";

import Link from "next/link";
import { useDashboard } from "@/components/AppShell";
import AlertsPanel from "@/components/AlertsPanel";
import StatsCards from "@/components/StatsCards";
import { fmtDate } from "@/lib/api";
import { ArrowRightIcon } from "@/components/icons";

export default function OverviewPage() {
  const { stats, businesses, alerts, markSeen, markAllSeen, alertsBusy } = useDashboard();

  const attention = businesses.filter((b) => b.status === "backoff" || b.status === "parked");
  const recent = alerts.slice(0, 5);

  return (
    <>
      <div className="page-head">
        <h2>Overview</h2>
        <span className="section-hint">crawler status, totals &amp; open alerts</span>
      </div>

      {/* Quick links lead the page: Businesses and Reviews are the two places
          an operator actually goes, and they carry the same totals as the
          stat tiles below, so they are not repeated down there. */}
      <div className="grid-2 quick-links">
        <Link className="stat-card quick-link" href="/dashboard/businesses">
          <div className="label">Businesses</div>
          <div className="value">{businesses.length}</div>
          <div className="muted">add, edit &amp; rescan listings</div>
        </Link>
        <Link className="stat-card quick-link" href="/dashboard/reviews">
          <div className="label">Reviews</div>
          <div className="value">{stats ? stats.reviews : "…"}</div>
          <div className="muted">stored Google Maps reviews</div>
        </Link>
      </div>

      <StatsCards stats={stats} />

      <div className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>Needs attention</h2>
            <Link className="muted" href="/businesses">
              Open businesses <ArrowRightIcon />
            </Link>
          </div>
          {attention.length === 0 ? (
            <p className="empty">
              All businesses healthy. No backoff or parked listings right now.
            </p>
          ) : (
            <div className="scroll-list">
              {attention.map((b) => (
                <div className="alert-item" key={b.id}>
                  <div className="msg">
                    <div>{b.name}</div>
                    <div className="meta">
                      <span className={b.status === "parked" ? "sev-danger" : "sev-warn"}>
                        {b.status}
                      </span>
                      {b.status === "backoff" && b.consecutive_blocks > 0
                        ? ` · block #${b.consecutive_blocks}`
                        : ""}
                      {b.status === "parked" && b.parked_until
                        ? ` until ${fmtDate(b.parked_until)}`
                        : ""}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <AlertsPanel
          alerts={recent}
          businesses={businesses}
          onSeen={markSeen}
          onSeenAll={markAllSeen}
          busyAll={alertsBusy}
          openTotal={alerts.filter((a) => !a.seen).length}
          total={alerts.length}
        />
      </div>
    </>
  );
}


