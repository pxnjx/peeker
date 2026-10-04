"use client";

import { useState } from "react";
import type { BusinessCreate } from "@/lib/api";
import { isHttpUrl } from "@/lib/api";
import { CloseIcon } from "@/components/icons";

export default function AddBusinessForm({
  onAdd,
}: {
  onAdd: (payload: BusinessCreate) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [mapsUrl, setMapsUrl] = useState("");
  const [kind, setKind] = useState<"own" | "competitor">("own");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    if (!name.trim() || !mapsUrl.trim()) {
      setError("Name and Google Maps URL are required.");
      return;
    }
    if (!isHttpUrl(mapsUrl)) {
      setError("Enter a valid Google Maps URL (https://maps.google.com/...).");
      return;
    }
    setBusy(true);
    try {
      // No `enqueue` in the payload: the backend defaults it to true, so a new
      // listing is always queued for its first scrape. There is no opt-out.
      await onAdd({ name: name.trim(), maps_url: mapsUrl.trim(), kind });
      setOk(`Added “${name.trim()}” — queued for a scrape.`);
      setName("");
      setMapsUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit} noValidate>
      <h2>Add Business</h2>
      <p className="section-hint" style={{ margin: "calc(var(--space-1) * -1) 0 var(--space-3)" }}>
        The name must match the Google listing. CSV performance rows attach by this name.
      </p>
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
      {ok && (
        <div className="success-banner" role="status">
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
      <div className="row">
        <div className="field">
          <label htmlFor="biz-name">Name</label>
          <input
            id="biz-name"
            type="text"
            placeholder="e.g. Pizza Hut Sudirman"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError(null);
            }}
          />
        </div>
        <div className="field" style={{ flex: 2 }}>
          <label htmlFor="biz-url">Google Maps URL</label>
          <input
            id="biz-url"
            type="url"
            placeholder="https://maps.google.com/..."
            value={mapsUrl}
            onChange={(e) => {
              setMapsUrl(e.target.value);
              setError(null);
            }}
          />
        </div>
        <div className="field" style={{ maxWidth: 160 }}>
          <label htmlFor="biz-kind">Kind</label>
          <select
            id="biz-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as "own" | "competitor")}
          >
            <option value="own">Own</option>
            <option value="competitor">Competitor</option>
          </select>
        </div>
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Adding…" : "Add"}
        </button>
      </div>
    </form>
  );
}
