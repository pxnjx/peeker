/**
 * The Peeker map-pin mark. One geometry shared by the sidebar, marketing nav
 * and login wordmark; the raster assets in public/ are generated from the
 * same path via tools/generate-brand-assets.ps1.
 *
 * The mark stands alone — no plate behind it — so the silhouette has to carry
 * the identity by itself: a solid pin body, a ring punched with evenodd, and an
 * electric-blue dot at the centre. That dot is the same accent the PWA icon
 * uses, which is what keeps the two reading as one brand now that the frame is
 * gone. `--accent` is tokenised (and already theme-lifted for dark), with the
 * Substack blue as a literal fallback.
 */
export default function BrandPin({ size = 18 }: { size?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} focusable="false" aria-hidden="true">
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M32 10c-8.837 0-16 7.163-16 16 0 11.5 12.8 23.8 14.6 25.3a2.1 2.1 0 0 0 2.8 0C35.2 49.8 48 37.5 48 26c0-8.837-7.163-16-16-16zm0 8.5a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15z"
      />
      <circle cx="32" cy="26" r="3.2" fill="var(--accent, #0000ee)" />
    </svg>
  );
}
