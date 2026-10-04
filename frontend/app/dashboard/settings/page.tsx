"use client";

import SettingsPanel from "@/components/SettingsPanel";

/**
 * Settings keeps its own heading: password + database tools are not part of
 * the crawler dashboard's data flow. The auto-refresh picker lives here now
 * too, but SettingsPanel reads it from the dashboard context.
 */
export default function SettingsPage() {
  return (
    <>
      <div className="page-head">
        <h2>Settings</h2>
        <span className="section-hint">
          auto-refresh interval, password &amp; database backup / restore
        </span>
      </div>
      <SettingsPanel />
    </>
  );
}
