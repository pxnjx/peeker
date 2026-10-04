/**
 * A real component preview: the dashboard's own classes with sample data, so
 * the hero shows the product itself instead of a hand-drawn fake screenshot.
 * The caption says the numbers are samples, which keeps the "no fake data"
 * rule honest.
 */
const SAMPLE_DISTRIBUTION = [
  { stars: 5, count: 412, pct: 58 },
  { stars: 4, count: 131, pct: 19 },
  { stars: 3, count: 74, pct: 10 },
];

export default function PreviewPanel() {
  return (
    <div className="preview" role="img" aria-label="Preview of the Peeker analyze view, sample data">
      <div className="preview-bar">
        <span className="preview-label">Analyze</span>
        <span className="preview-label">newest 500 stored</span>
      </div>

      <div className="stats-grid two">
        <div className="stat-card">
          <div className="label">Avg rating</div>
          <div className="value">4.12</div>
          <div className="muted">across 500 stored</div>
        </div>
        <div className="stat-card">
          <div className="label">Rating gap</div>
          <div className="value delta good">+0.18</div>
          <div className="muted">yours vs them</div>
        </div>
      </div>

      {SAMPLE_DISTRIBUTION.map((row) => (
        <div className="bar-row" key={row.stars}>
          <span className="bar-label">{row.stars} stars</span>
          <div className="bar-track">
            <div
              className={`bar-fill${row.stars === 5 ? " strong" : ""}`}
              style={{ width: `${Math.max(2, row.pct)}%` }}
            />
          </div>
          <span className="bar-value">
            {row.count} · {row.pct}%
          </span>
        </div>
      ))}

      <p className="preview-caption">Sample data, rendered with the real Analyze components.</p>
    </div>
  );
}
