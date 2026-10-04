import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/** Open the landing page to crawlers; keep the session-gated app and the API out. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/dashboard", "/login", "/api/"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
