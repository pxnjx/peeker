"use client";

import AnalyzePanel from "@/components/AnalyzePanel";
import { useDashboard } from "@/components/AppShell";

export default function AnalyzePage() {
  const { businesses, stats } = useDashboard();

  return (
    <>
      <div className="page-head">
        <h2>Analyze</h2>
        <span className="section-hint">
          ratings, comment coverage &amp; own vs competitor standing
        </span>
      </div>

      <AnalyzePanel businesses={businesses} stats={stats} />
    </>
  );
}
