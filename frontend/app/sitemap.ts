import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * Public surface only. The dashboard lives behind a session, so it is
 * deliberately absent here (and disallowed in robots.txt).
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    {
      url: `${SITE_URL}/`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 1,
    },
  ];
}
