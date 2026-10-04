"use client";

import { useDashboard } from "@/components/AppShell";
import AlertsPanel from "@/components/AlertsPanel";

export default function AlertsPage() {
  const { alerts, businesses, markSeen, markAllSeen, alertsBusy } = useDashboard();
  const open = alerts.filter((a) => !a.seen).length;

  return (
    <>
      <div className="page-head">
        <h2>Alerts</h2>
        <span className="section-hint">
          {open > 0 ? `${open} open: rating drops and review bursts` : "rating drops and review bursts"}
        </span>
      </div>
      <AlertsPanel
        alerts={alerts}
        businesses={businesses}
        onSeen={markSeen}
        onSeenAll={markAllSeen}
        busyAll={alertsBusy}
      />
    </>
  );
}
