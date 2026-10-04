"use client";

/**
 * Settings: reset password + database backup/restore, mirroring Kwerry's
 * Settings page (03 · DATA). Backup downloads a full SQLite copy; restore
 * swaps an uploaded .db over the live file and asks for a backend restart.
 */
import { useState } from "react";
import { api } from "@/lib/api";
import { CloseIcon, DownloadIcon, UploadIcon } from "@/components/icons";
import {
  DEFAULT_REFRESH,
  REFRESH_OPTIONS,
  useDashboard,
} from "@/lib/useDashboardData";
import type { RefreshInterval } from "@/lib/useDashboardData";

/** Kwerry .settings-head: eyebrow + title + muted description. */
function PanelHead({
  eyebrow,
  title,
  desc,
}: {
  eyebrow: string;
  title: string;
  desc: string;
}) {
  return (
    <div className="settings-head">
      <span className="eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      <p className="muted settings-desc">{desc}</p>
    </div>
  );
}

export default function SettingsPanel() {
  const { refreshMs, changeRefresh } = useDashboard();
  const [showPw, setShowPw] = useState({ cur: false, next: false, again: false });
  const [pwMsg, setPwMsg] = useState("");
  const [pwOk, setPwOk] = useState(false);
  const [pwBusy, setPwBusy] = useState(false);
  const [backupMsg, setBackupMsg] = useState("");
  const [backupErr, setBackupErr] = useState(false);
  const [backupBusy, setBackupBusy] = useState(false);
  const [restoreBusy, setRestoreBusy] = useState(false);

  /** Change the signed-in account's password (frontend /api/password route). */
  async function changePassword(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPwMsg("");
    setPwOk(false);
    const form = new FormData(e.currentTarget);
    const cur = String(form.get("curPass") ?? "");
    const next = String(form.get("newPass") ?? "");
    const again = String(form.get("newPass2") ?? "");
    if (next !== again) {
      setPwMsg("New passwords do not match.");
      return;
    }
    if (next.length < 8) {
      setPwMsg("New password must be at least 8 characters.");
      return;
    }
    setPwBusy(true);
    try {
      const res = await fetch("/api/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currentPassword: cur, newPassword: next }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(body?.detail ?? res.statusText);
      }
      e.currentTarget.reset();
      setShowPw({ cur: false, next: false, again: false });
      setPwOk(true);
      setPwMsg("Password saved.");
    } catch (err) {
      setPwMsg(err instanceof Error ? err.message : "Could not change password.");
    } finally {
      setPwBusy(false);
    }
  }

  async function downloadBackup() {
    setBackupMsg("");
    setBackupErr(false);
    setBackupBusy(true);
    try {
      await api.downloadBackup();
    } catch (err) {
      setBackupMsg(err instanceof Error ? err.message : "Backup failed.");
      setBackupErr(true);
    } finally {
      setBackupBusy(false);
    }
  }

  async function restoreFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!window.confirm("Restore replaces the current database. Keep a backup first. Continue?")) {
      return;
    }
    setBackupMsg("");
    setBackupErr(false);
    setRestoreBusy(true);
    try {
      const out = await api.restoreBackup(file);
      setBackupMsg(out.message);
    } catch (err) {
      setBackupMsg(err instanceof Error ? err.message : "Restore failed.");
      setBackupErr(true);
    } finally {
      setRestoreBusy(false);
    }
  }

  return (
    <div className="settings-grid">
      {/* Security leads and owns the left track at full height (grid-row spans
          both). Data Sync and Data stack in the right track, so DOM order is
          Security, Data Sync, Data and the grid places them — that keeps the
          reading and tab order matching what is on screen. */}
      <article className="panel settings-panel settings-panel--lead">
        <PanelHead
          eyebrow="01 · SECURITY"
          title="Reset password"
          desc="Change the password of the account you are signed in with."
        />
        <form className="form-stack" onSubmit={changePassword}>
          <div className="field">
            <label htmlFor="curPass">Current password</label>
            <div className="input-wrap">
              <input
                id="curPass"
                name="curPass"
                type={showPw.cur ? "text" : "password"}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className="input-toggle"
                onClick={() => setShowPw((s) => ({ ...s, cur: !s.cur }))}
                aria-label={showPw.cur ? "Hide current password" : "Show current password"}
              >
                {showPw.cur ? "Hide" : "Show"}
              </button>
            </div>
          </div>
          <div className="field">
            <label htmlFor="newPass">New password</label>
            <div className="input-wrap">
              <input
                id="newPass"
                name="newPass"
                type={showPw.next ? "text" : "password"}
                autoComplete="new-password"
                required
                minLength={8}
              />
              <button
                type="button"
                className="input-toggle"
                onClick={() => setShowPw((s) => ({ ...s, next: !s.next }))}
                aria-label={showPw.next ? "Hide new password" : "Show new password"}
              >
                {showPw.next ? "Hide" : "Show"}
              </button>
            </div>
          </div>
          <div className="field">
            <label htmlFor="newPass2">Confirm new password</label>
            <div className="input-wrap">
              <input
                id="newPass2"
                name="newPass2"
                type={showPw.again ? "text" : "password"}
                autoComplete="new-password"
                required
                minLength={8}
              />
              <button
                type="button"
                className="input-toggle"
                onClick={() => setShowPw((s) => ({ ...s, again: !s.again }))}
                aria-label={showPw.again ? "Hide confirmation" : "Show confirmation"}
              >
                {showPw.again ? "Hide" : "Show"}
              </button>
            </div>
          </div>
          <div className="form-actions">
            <button type="submit" className="primary" disabled={pwBusy}>
              {pwBusy ? "Saving…" : "Save password"}
            </button>
          </div>
        </form>
        {pwMsg && (
          <div
            className={`banner-stack ${pwOk ? "success-banner" : "error-banner"}`}
            role="alert"
          >
            {pwMsg}
            <button
              type="button"
              className="banner-dismiss"
              onClick={() => setPwMsg("")}
              aria-label="Dismiss message"
            >
              <CloseIcon />
            </button>
          </div>
        )}
      </article>

      <article className="panel settings-panel">
        <PanelHead
          eyebrow="02 · DATA SYNC"
          title="Auto-refresh"
          desc="How often the dashboard re-fetches stats, businesses and alerts. Manual means data only updates when you press Refresh."
        />
        <label className="refresh-setting">
          <span className="muted">Refresh interval</span>
          <select
            aria-label="Auto-refresh interval"
            value={refreshMs === null ? DEFAULT_REFRESH : refreshMs}
            onChange={(e) => changeRefresh(Number(e.target.value) as RefreshInterval)}
          >
            {REFRESH_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </article>

      <article className="panel settings-panel">
        <PanelHead
          eyebrow="03 · DATA"
          title="Database backup"
          desc="Download a full SQLite backup (businesses, reviews, performance, alerts). Restore replaces the current database, so keep a backup first."
        />
        {backupMsg && (
          <div className={backupErr ? "error-banner" : "success-banner"} role="alert">
            {backupMsg}
            <button
              type="button"
              className="banner-dismiss"
              onClick={() => setBackupMsg("")}
              aria-label="Dismiss message"
            >
              <CloseIcon />
            </button>
          </div>
        )}
        <div className="backup-actions">
          <button
            type="button"
            className="primary"
            onClick={() => void downloadBackup()}
            disabled={backupBusy}
          >
            <DownloadIcon />
            {backupBusy ? "Preparing…" : "Download backup"}
          </button>
          <label className="ghost file-btn">
            <UploadIcon />
            {restoreBusy ? "Restoring…" : "Restore from file"}
            <input
              type="file"
              accept=".db,application/octet-stream"
              hidden
              onChange={restoreFile}
            />
          </label>
        </div>
        <p className="muted settings-note">
          After restore, restart the backend server to load the restored data.
        </p>
      </article>
    </div>
  );
}
