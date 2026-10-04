import type { Metadata } from "next";

/** Title only: this layout exists so the route can declare its own metadata. */
export const metadata: Metadata = {
  title: "Performance",
};

export default function PerformanceLayout({ children }: { children: React.ReactNode }) {
  return children;
}
