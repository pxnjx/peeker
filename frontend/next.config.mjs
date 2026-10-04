/** @type {import('next').NextConfig} */

/**
 * Where the backend lives for the /backend proxy below. It reads the same
 * NEXT_PUBLIC_API_URL the app uses: absolute means "forward /backend/* there",
 * relative means "same origin, no proxy needed". Default is the local FastAPI port.
 *
 * BACKEND_ORIGIN wins over NEXT_PUBLIC_API_URL because it only moves the *proxy*,
 * leaving API_URL in lib/api.ts relative ("/backend"). That keeps the browser on a
 * single origin, so the host-scoped dashboard session cookie keeps working no matter
 * which port uvicorn happens to run on - run.bat uses it to hand Next a random port.
 */
const API_TARGET =
  process.env.BACKEND_ORIGIN ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  /* The dev-only Next.js badge sits fixed in the bottom-left corner by default, which is
     exactly where the sidebar's "auto-refresh" status line lives (and the mobile bottom
     nav owns the bottom edge). The app owns its own corners, so the badge is off. */
  devIndicators: false,

  /**
   * The dashboard moved behind /dashboard when the landing page took over "/".
   * Old links keep working through permanent redirects instead of 404ing.
   */
  async redirects() {
    return ["businesses", "analyze", "performance", "reviews", "alerts"].map((slug) => ({
      source: `/${slug}`,
      destination: `/dashboard/${slug}`,
      permanent: true,
    }));
  },

  /**
   * Same-origin API proxy. The dashboard session cookie is host-scoped, so the
   * browser can only carry it to the backend when both share an origin. The app
   * therefore talks to the relative "/backend/*", and Next.js forwards those
   * requests server-side to FastAPI - including the cookie, invisible to page JS.
   * An absolute NEXT_PUBLIC_API_URL keeps working for direct calls (then the
   * cookie must be visible on that host too).
   */
  async rewrites() {
    if (API_TARGET.startsWith("/")) return [];
    return [{ source: "/backend/:path*", destination: `${API_TARGET}/:path*` }];
  },
};

export default nextConfig;

