"use client";

import { useState } from "react";
import type { Business, BusinessUpdate } from "@/lib/api";
import { isHttpUrl } from "@/lib/api";
import { useEscape } from "@/lib/useEscape";
import { CloseIcon } from "@/components/icons";

/**
 * Edit dialog for a tracked listing: the name (CSV performance rows attach by it) and the
 * Google Maps link the scraper follows. URL validation mirrors AddBusinessForm so both forms
 * accept exactly the same links.
 */
export default function BusinessEditModal({
  business,
  busy,
  onClose,
  onSave,
}: {
  business: Business;
  busy: boolean;
  onClose: () => void;
  onSave: (patch: BusinessUpdate) => Promise<void>;
}) {
  const [name, setName] = useState(business.name);
  const [mapsUrl, setMapsUrl] = useState(business.maps_url);
  const [error, setError] = useState<string | null>(null);

  useEscape(onClose);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    if (!isHttpUrl(mapsUrl)) {
      setError("Enter a valid Google Maps URL (https://maps.google.com/...).");
      return;
    }
    try {
      await onSave({ name: name.trim(), maps_url: mapsUrl.trim() });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err)); // e.g. 409 name already exists
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        className="modal"
        onSubmit={submit}
        noValidate
        role="dialog"
        aria-modal="true"
        aria-labelledby="biz-edit-title"
      >
        <div className="modal-head">
          <div>
            <h3 id="biz-edit-title">Edit Business</h3>
            <div className="modal-sub">
              <span className={`kind-badge ${business.kind}`}>{business.kind}</span>
              <span className={`badge ${business.status}`}>{business.status}</span>
            </div>
          </div>
          <button
            type="button"
            className="banner-dismiss"
            onClick={onClose}
            aria-label="Close editor"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="modal-body form-stack">
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
          <div className="field">
            <label htmlFor="edit-biz-name">Name</label>
            <input
              id="edit-biz-name"
              type="text"
              autoFocus
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
            />
            <span className="field-hint">
              Must match the Google listing. Performance CSV rows attach by this name.
            </span>
          </div>
          <div className="field">
            <label htmlFor="edit-biz-url">Google Maps URL</label>
            <input
              id="edit-biz-url"
              type="url"
              value={mapsUrl}
              onChange={(e) => {
                setMapsUrl(e.target.value);
                setError(null);
              }}
            />
            <span className="field-hint">The link the next scrape follows.</span>
          </div>
        </div>

        <div className="modal-foot">
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
