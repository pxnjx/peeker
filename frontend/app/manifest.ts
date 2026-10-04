import type { MetadataRoute } from "next";
import { SITE_DESCRIPTION, SITE_NAME, SITE_TITLE } from "@/lib/site";

/**
 * PWA manifest. Icons are the full-bleed (maskable) builds from
 * tools/generate-brand-assets.ps1 so launchers can crop to any shape.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    // From SITE_TITLE, not a second literal spelling of the tagline: the manifest
    // name and the browser tab title then cannot drift apart.
    name: SITE_TITLE,
    short_name: SITE_NAME,
    description: SITE_DESCRIPTION,
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#313131",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml" },
    ],
  };
}
