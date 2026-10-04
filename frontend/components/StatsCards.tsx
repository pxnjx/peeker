import type { Stats } from "@/lib/api";

/* A stat card stays neutral unless the number itself reports a state, which is
   the only thing that earns a hue (rule R2 in app/globals.css). This row is
   crawler health only, so every tile maps to a state the operator scans.
   Businesses and Reviews are deliberately absent: the Overview's quick links at
   the top of the page already carry those two totals with their destinations,
   and a second copy further down just repeated the same number. */
const CARDS: { key: keyof Stats; label: string; tone?: string }[] = [
  { key: "queued", label: "Queued" },
  { key: "scraping", label: "Scraping", tone: "tone-warn" },
  { key: "idle", label: "Idle", tone: "tone-good" },
  { key: "backoff", label: "Backoff", tone: "tone-warn" },
  { key: "parked", label: "Parked", tone: "tone-danger" },
  { key: "open_alerts", label: "Open Alerts" },
];

export default function StatsCards({ stats }: { stats: Stats | null }) {
  return (
    <div className="stats-grid">
      {CARDS.map(({ key, label, tone }) => {
        // Open alerts only shout when there is something to act on.
        const cls =
          key === "open_alerts"
            ? stats && stats.open_alerts > 0
              ? "stat-card tone-danger"
              : "stat-card"
            : `stat-card${tone ? ` ${tone}` : ""}`;
        return (
          <div className={cls} key={key}>
            <div className="label">{label}</div>
            <div className="value">{stats ? stats[key] : "…"}</div>
          </div>
        );
      })}
    </div>
  );
}
