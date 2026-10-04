import type { Metadata, Viewport } from "next";
import {
  SITE_DESCRIPTION,
  SITE_NAME,
  SITE_TAGLINE,
  SITE_TITLE,
  SITE_URL,
} from "@/lib/site";
import "./globals.css";

/* Type is the Substack system stack (substack-DESIGN.md): no webfont,
   no Google Fonts link. --font-sans lives in tokens.css. */

const OG_IMAGE = {
  url: "/og.png",
  width: 1200,
  height: 630,
  alt: `${SITE_NAME} wordmark: a white map pin on an ink tile, above the tagline ${SITE_TAGLINE}`,
};

/**
 * metadataBase makes Next resolve every relative OG/Twitter/sitemap URL against
 * SITE_URL, which falls back to localhost when NEXT_PUBLIC_SITE_URL is unset. That
 * publishes perfectly valid tags pointing at nobody's server, and nothing fails
 * loudly, so say so once at build time instead.
 */
if (!process.env.NEXT_PUBLIC_SITE_URL) {
  console.warn(
    "[peeker] NEXT_PUBLIC_SITE_URL is not set — OpenGraph, Twitter card and sitemap " +
      "URLs will be built from the fallback http://localhost:3001. Set it in " +
      "frontend/.env.local before publishing.",
  );
}

/**
 * Every title, description and icon the crawler sees. Per-route titles come
 * from the small layout files in app/<route>/, which inherit the template.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: SITE_TITLE,
    template: `%s · ${SITE_NAME}`,
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  keywords: [
    "Google Maps reviews",
    "competitor monitoring",
    "review alerts",
    "rating tracking",
    "Google Business Profile export",
    "self-hosted",
    "local review monitoring",
    "review management",
  ],
  authors: [{ name: SITE_NAME }],
  category: "business",
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: SITE_NAME,
    locale: "en_US",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    images: [OG_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    images: [OG_IMAGE.url],
  },
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "48x48", type: "image/x-icon" },
    ],
    apple: "/apple-touch-icon.png",
  },
  manifest: "/manifest.webmanifest",
  robots: { index: true, follow: true },
};

/** schema.org descriptor so search and link previews identify the app. */
const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: SITE_NAME,
  description: SITE_DESCRIPTION,
  url: SITE_URL,
  applicationCategory: "BusinessApplication",
  applicationSubCategory: "Review monitoring",
  operatingSystem: "Any",
  browserRequirements: "Requires JavaScript",
  image: [OG_IMAGE.url],
  isAccessibleForFree: true,
  featureList: [
    "Scheduled re-scrapes of Google Maps ratings and review counts",
    "Full review text and comment coverage, not just the star score",
    "Side-by-side comparison against tracked competitors",
    "Alerts on rating drops and review bursts",
    "Google Business Profile performance CSV import",
    "Local SQLite storage with full backup and restore",
  ],
};


export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#121212" },
  ],
};

/**
 * Resolves the theme before the first paint so a dark-mode reload never flashes white.
 * Runs synchronously in <head>; keeps the choice in localStorage across visits.
 */
const THEME_SCRIPT = `
(function () {
  try {
    var stored = window.localStorage.getItem("peeker.theme");
    var theme =
      stored === "light" || stored === "dark"
        ? stored
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    document.documentElement.dataset.theme = theme;
  } catch (e) {
    document.documentElement.dataset.theme = "light";
  }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            // "<" escaped so the payload can never terminate the script element.
            __html: JSON.stringify(JSON_LD).replace(/</g, "\\u003c"),
          }}
        />
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}

