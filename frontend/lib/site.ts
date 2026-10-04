/**
 * Single source for everything the metadata layer says about the site: layout
 * metadata, per-route titles, JSON-LD, manifest, robots and sitemap all read
 * from here so title and description can never drift apart.
 *
 * NEXT_PUBLIC_SITE_URL is the public origin (for absolute OpenGraph URLs).
 * The fallback only exists so a local build produces valid absolute links.
 */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3001";

export const SITE_NAME = "Peeker";

/**
 * ~51 characters so it survives a SERP title without truncation. The
 * self-hosted angle is the differentiator: the dashboard runs against a local
 * SQLite file the operator owns, with no third-party service in the loop.
 */
export const SITE_TITLE = "Peeker — self-hosted Google Maps review monitoring";

export const SITE_DESCRIPTION =
  "Peeker watches your Google Maps listing and the competitors around it: scheduled re-scrapes of ratings and full review text, alerts when a rating drops or reviews arrive in a burst, and Google Business Profile performance imports — all in a local database you own.";

/** Short form used where a full sentence does not fit, e.g. Twitter cards.
    Unchanged from the line baked into public/og.png by tools/generate-brand-assets.ps1
    so the card image and the copy agree. */
export const SITE_TAGLINE = "Google Maps review and competitor monitoring, in one dashboard.";
