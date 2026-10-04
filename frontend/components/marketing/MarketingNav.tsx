import Link from "next/link";

import BrandPin from "@/components/BrandPin";
import ThemeToggle from "@/components/ThemeToggle";

/**
 * Landing navigation, Kwerry-shaped: sticky bar, brand tile + name/tagline on
 * the left, theme switch alone on the right. Signing in lives in the hero and
 * closing CTAs instead, so the bar carries no link of its own.
 *
 * Still a Server Component: only <ThemeToggle /> hydrates, so the rest of the
 * bar ships as plain markup.
 */
export default function MarketingNav() {
  return (
    <header className="m-nav">
      <div className="shell m-nav-inner">
        <Link className="m-wordmark" href="/">
          <span className="brand-mark" aria-hidden="true">
            <BrandPin size={20} />
          </span>
          <span className="brand-text">
            <strong>Peeker</strong>
            <span>Google Maps review monitoring</span>
          </span>
        </Link>
        {/* Anchored to .m-nav's right edge (see .m-nav .theme-toggle), not to
            the content column, so it clears the shell on wide screens. */}
        <ThemeToggle />
      </div>
    </header>
  );
}
