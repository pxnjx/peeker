"use client";

import { useDashboard } from "@/components/AppShell";
import PerformancePanel from "@/components/PerformancePanel";

export default function PerformancePage() {
  const { businesses } = useDashboard();

  return (
    <>
      <div className="page-head">
        <h2>Performance</h2>
        <span className="section-hint">
          upload the Google Business Profile CSV. Account exports split per location
        </span>
      </div>
      <PerformancePanel businesses={businesses} />
    </>
  );
}
