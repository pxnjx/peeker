"use client";

import { useDashboard } from "@/components/AppShell";
import ReviewsViewer from "@/components/ReviewsViewer";

export default function ReviewsPage() {
  const { businesses } = useDashboard();

  return (
    <>
      <div className="page-head">
        <h2>Reviews</h2>
        <span className="section-hint">stored Google Maps reviews, newest first</span>
      </div>
      <ReviewsViewer businesses={businesses} />
    </>
  );
}
