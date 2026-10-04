import type { Metadata } from "next";

/** Title only: this layout exists so the route can declare its own metadata. */
export const metadata: Metadata = {
  title: "Reviews",
};

export default function ReviewsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
