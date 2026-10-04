import Link from "next/link";

import PreviewPanel from "@/components/marketing/PreviewPanel";

/**
 * The hero, and the only filled accent pill in its band.
 *
 * Measured stack discipline: eyebrow, headline (one line at desktop), subtext
 * under 20 words, two CTAs, plus a real component preview as the visual. No
 * tagline under the CTAs, no trust strip, no pricing teaser.
 *
 * Motion is CSS (`rise` / `rise-1..4` in globals.css), so this stays a Server
 * Component and the public page ships no JavaScript for animation at all.
 */
export default function Hero() {
  return (
    <section className="hero-band">
      <div className="shell hero-grid">
        <div>
          <p className="eyebrow rise rise-1">Google Maps monitoring</p>
          <h1 className="hero-title rise rise-2">
            Your Google Maps reviews, watched around the clock.
          </h1>
          <p className="hero-sub rise rise-3">
            Peeker scrapes your listings and the competitors around them, then reports what changed:
            ratings, comment volume and review text.
          </p>
          <div className="cta-row rise rise-4">
            <Link className="m-cta" href="/login">
              Open the dashboard
            </Link>
            <a className="m-cta secondary" href="#how">
              See how it works
            </a>
          </div>
        </div>
        <div className="rise rise-3">
          <PreviewPanel />
        </div>
      </div>
    </section>
  );
}
