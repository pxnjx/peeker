/**
 * Landing footer, matching Kwerry: one quiet studio credit line.
 */
export default function SiteFooter() {
  return (
    <footer className="site-footer landing-foot">
      {/* The .shell wrapper puts the credit on the same 1200px content column as
          every other element; without it the footer text sat hard against the
          right edge of the window. */}
      <div className="shell landing-foot-inner">
        <span>
          (c) 2026{" "}
          <a
            className="footer-link"
            href="https://scrambledhead.pxnjx.com/"
            target="_blank"
            rel="noopener"
          >
            <strong>scrambled_head.studio</strong>
          </a>{" "}
          · All scribbles reserved.
        </span>
      </div>
    </footer>
  );
}
