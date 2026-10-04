import type { Metadata } from "next";
import Link from "next/link";

import Hero from "@/components/marketing/Hero";
import MarketingNav from "@/components/marketing/MarketingNav";
import SiteFooter from "@/components/marketing/SiteFooter";
import { CheckIcon, StarIcon, StarOutlineIcon } from "@/components/icons";
import { SITE_TAGLINE } from "@/lib/site";

/** The landing is the canonical public page, so its metadata is explicit. */
export const metadata: Metadata = {
  alternates: { canonical: "/" },
  openGraph: { url: "/" },
};

/** Four things the crawler watches, phrased the way an operator experiences them. */
const WATCH = [
  {
    title: "New comments as they land",
    body: "Author, rating and the text itself, kept in full so you read the comment instead of guessing from the score.",
  },
  {
    title: "Average rating and volume",
    body: "The score, how many reviews sit behind it, and how the mix of one and five star entries moves month by month.",
  },
  {
    title: "The listings around you",
    body: "Rating and review volume for the businesses competing for the same search, side by side with yours.",
  },
  {
    title: "Whether the data is fresh",
    body: "Queue, backoff and parked states, so a stale number is visible rather than quietly wrong.",
  },
];

/**
 * The landing stays a Server Component: scrolling motion is CSS and the content
 * is static, so the only hydrated island on the page is the nav's theme switch.
 * `scroll-behavior: smooth` on html makes the in-page anchors glide.
 */
export default function LandingPage() {
  return (
    <div className="marketing">
      {/* The measured backdrop: marketing only, never behind product data. */}
      <div className="mesh" aria-hidden="true" />
      <MarketingNav />

      <main>
        <Hero />

        <section className="band" id="product">
          <div className="shell">
            <div className="reveal">
              <h2 className="section-heading">What it watches</h2>
              <p className="section-lead">
                Four things, checked on the schedule you set. Everything else the dashboard shows
                is built from these.
              </p>
            </div>
            <div className="watch-grid reveal">
              {WATCH.map((item) => (
                <div className="watch-cell" key={item.title}>
                  <h3>{item.title}</h3>
                  <p>{item.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="band">
          <div className="shell feature">
            <div className="feature-text reveal">
              <h2>Comment coverage, not just the score</h2>
              <p>
                A rating tells you something moved. The comment tells you what to fix. Peeker keeps
                the text, the author and the timestamp for every review it collects.
              </p>
              <ul className="feature-list">
                <li>
                  <CheckIcon /> Filter to one and two star reviews in a click
                </li>
                <li>
                  <CheckIcon /> Comment coverage per business, so you know how many are silent
                </li>
                <li>
                  <CheckIcon /> Export the current view as CSV for the week you are reviewing
                </li>
              </ul>
            </div>
            <div className="feature-visual reveal">
              <div className="review-card">
                <div className="review-head">
                  <span className="review-author">Sample review</span>
                  <span className="review-stars" role="img" aria-label="2 out of 5 stars">
                    <StarIcon />
                    <StarIcon />
                    <StarOutlineIcon />
                    <StarOutlineIcon />
                    <StarOutlineIcon />
                  </span>
                  <span className="muted">2.0</span>
                  <span className="muted">14 Sep 2026</span>
                </div>
                <p className="review-text">
                  The table was booked for 19:00 and we sat down at 19:40.
                </p>
              </div>
              <p className="preview-caption">
                A sample review, rendered with the real review card from the Reviews view.
              </p>
            </div>
          </div>
        </section>

        <section className="band">
          <div className="shell feature flip">
            <div className="feature-text reveal">
              <h2>Your rating against the market</h2>
              <p>
                Every listing you track is compared on the same two numbers: the weighted rating
                and the review volume behind it. The gap is the headline, the table is the detail.
              </p>
              <ul className="feature-list">
                <li>
                  <CheckIcon /> Own and competitor listings in one comparison
                </li>
                <li>
                  <CheckIcon /> Review-weighted averages, so one listing cannot skew the group
                </li>
                <li>
                  <CheckIcon /> Rating distribution per side, from one to five stars
                </li>
              </ul>
            </div>
            <div className="feature-visual reveal">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Business</th>
                      <th>Kind</th>
                      <th className="num">Rating</th>
                      <th className="num">Reviews</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>
                        <strong>Your listing</strong>
                      </td>
                      <td>
                        <span className="kind-badge own">Yours</span>
                      </td>
                      <td className="num">4.41</td>
                      <td className="num">1,204</td>
                    </tr>
                    <tr>
                      <td>Warung Kopi Senja</td>
                      <td>
                        <span className="kind-badge competitor">Competitor</span>
                      </td>
                      <td className="num">4.23</td>
                      <td className="num">861</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="preview-caption">Sample rows, rendered with the real comparison table.</p>
            </div>
          </div>
        </section>

        <section className="band band-cream" id="how">
          <div className="shell steps">
            <div className="reveal">
              <h2>How it works</h2>
              <p>
                Add the link once. Peeker keeps the schedule, waits out the rate limits and leaves
                the reading to you.
              </p>
            </div>
            <ol className="step-list reveal">
              <li>
                <strong className="step-verb">Add the Google Maps link</strong>
                <p className="step-body">Name and URL, and the first scrape starts right away.</p>
              </li>
              <li>
                <strong className="step-verb">Peeker scrapes on a schedule</strong>
                <p className="step-body">
                  Reviews, rating and review count refresh on the interval you pick.
                </p>
              </li>
              <li>
                <strong className="step-verb">Read the alerts</strong>
                <p className="step-body">
                  Rating drops and review bursts arrive as alerts you can mark as seen.
                </p>
              </li>
            </ol>
          </div>
        </section>

        <section className="band band-lg band-ink">
          <div className="shell reveal">
            <h2>Ready to see your listings in one place?</h2>
            <p>{SITE_TAGLINE}</p>
            <div className="cta-row">
              <Link className="m-cta" href="/login">
                Open the dashboard
              </Link>
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
