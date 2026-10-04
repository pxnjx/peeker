import type { Metadata } from "next";

/** Title only: this layout exists so the route can declare its own metadata. */
export const metadata: Metadata = {
  title: "Settings",
};

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
