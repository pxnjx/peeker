"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Business, Performance } from "@/lib/api";
import { EMPTY_VALUE, api, fmtStamp } from "@/lib/api";
import { CloseIcon, RefreshIcon, UploadIcon } from "@/components/icons";

type MetricKey =
  | "search_mobile"
  | "search_desktop"
  | "maps_mobile"
  | "maps_desktop"
  | "calls"
  | "directions"
  | "website_clicks";

const COLUMNS: { key: MetricKey; label: string; title: string }[] = [
  { key: "search_mobile", label: "Search · Mobile", title: "Google Search - Mobile" },
  { key: "search_desktop", label: "Search · Desktop", title: "Google Search - Desktop" },
  { key: "maps_mobile", label: "Maps · Mobile", title: "Google Maps - Mobile" },
  { key: "maps_desktop", label: "Maps · Desktop", title: "Google Maps - Desktop" },
  { key: "calls", label: "Calls", title: "Calls" },
  { key: "directions", label: "Directions", title: "Directions" },
  { key: "website_clicks", label: "Website Clicks", title: "Website clicks" },
];

export default function PerformancePanel({ businesses }: { businesses: Business[] }) {
  const [viewId, setViewId] = useState<number | null>(null);
  const [rows, setRows] = useState<Performance[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [fallbackId, setFallbackId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Default the view to the first business; keep it valid as the list changes.
  useEffect(() => {
    if (businesses.length === 0) {
      setViewId(null);
      return;
    }
    setViewId((cur) => (cur !== null && businesses.some((b) => b.id === cur) ? cur : businesses[0].id));
  }, [businesses]);

  // Rapid business switching fires overlapping GETs: only the newest one may render.
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const reqId = ++requestId.current;
    if (viewId === null) {
      setRows([]);
      return;
    }
    try {
      const list = await api.performance(viewId);
      if (reqId !== requestId.current) return;
      setRows(list);
    } catch (e) {
      if (reqId !== requestId.current) return;
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [viewId]);

  useEffect(() => {
    load();
  }, [load]);

  async function upload() {
    if (!file) {
      setErr("Choose a .csv file first.");
      return;
    }
    setBusy(true);
    setOk(null);
    setErr(null);
    try {
      const res = await api.uploadPerformance(file, fallbackId ? Number(fallbackId) : undefined);
      setFile(null);
      const input = document.getElementById("perf-file") as HTMLInputElement | null;
      if (input) input.value = "";
      const attached = res.attached_locations.length;
      const waiting = res.pending_locations.length;
      if (attached > 0) {
        setOk(
          `Imported ${res.imported} row(s); ${attached} location(s) matched` +
            (waiting > 0 ? `, ${waiting} stored pending (business not tracked yet)` : ""),
        );
        if (res.business_id !== null) setViewId(res.business_id); // follow the matched business
        await load();
      } else {
        setOk(
          `Saved ${res.imported} row(s) as pending for ${waiting} location(s). ` +
            "add them as businesses and the data attaches automatically.",
        );
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const totals = COLUMNS.map((c) => rows.reduce((sum, r) => sum + r[c.key], 0));

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>GBP performance export</h2>
      </div>
      <div className="row perf-controls">
        <div className="field" style={{ flex: "0 1 160px" }}>
          <label>Business shown</label>
          <select
            value={viewId ?? ""}
            onChange={(e) => setViewId(Number(e.target.value))}
            disabled={businesses.length === 0}
          >
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ flex: "0 1 270px" }}>
          <label>Fallback / override business (optional)</label>
          <select value={fallbackId} onChange={(e) => setFallbackId(e.target.value)}>
            <option value="">None</option>
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ flex: "1 1 380px" }}>
          <label>Google performance report (.csv), name auto-matched</label>
          <input
            id="perf-file"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        <button className="primary" onClick={upload} disabled={busy || !file}>
          {busy ? <RefreshIcon className="spin" /> : <><UploadIcon /> Upload</>}
        </button>
      </div>

      {ok && (
        <div className="success-banner" role="status" style={{ marginTop: "var(--space-3)" }}>
          {ok}
          <button
            type="button"
            className="banner-dismiss"
            onClick={() => setOk(null)}
            aria-label="Dismiss"
          >
            <CloseIcon />
          </button>
        </div>
      )}
      {err && (
        <div className="error-banner" role="alert" style={{ marginTop: "var(--space-3)" }}>
          {err}
          <button
            type="button"
            className="banner-dismiss"
            onClick={() => setErr(null)}
            aria-label="Dismiss error"
          >
            <CloseIcon />
          </button>
        </div>
      )}

      {viewId === null ? (
        <p className="empty">
          No business tracked yet. Upload a performance CSV above anyway: it stays pending and
          attaches automatically once you add the location.
        </p>
      ) : rows.length === 0 ? (
        <p className="empty">
          No performance data yet. Download the report from Google Business Profile and upload the
          .csv above.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Location</th>
                <th title="Reporting period of the uploaded CSV">Period</th>
                <th title="When this period's CSV was uploaded">Uploaded</th>
                {COLUMNS.map((c) => (
                  <th key={c.key} className="num" title={c.title}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.source_name || businesses.find((b) => b.id === r.business_id)?.name || EMPTY_VALUE}</td>
                  <td>{r.period}</td>
                  <td className="muted">{fmtStamp(r.imported_at)}</td>
                  {COLUMNS.map((c) => (
                    <td key={c.key} className="num">
                      {r[c.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3}>
                  <strong>Total</strong>
                </td>
                {COLUMNS.map((c, i) => (
                  <td key={c.key} className="num">
                    <strong>{totals[i]}</strong>
                  </td>
                ))}
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}