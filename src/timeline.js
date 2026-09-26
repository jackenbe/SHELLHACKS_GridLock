import { utilityColor } from "./colors";
import { fmtMonth, parseDate } from "./dates";

// Two rows on a shared year axis: when each project is being built.
// Known start date -> a bar from start to in-service. Only an in-service date -> a diamond.
export default function Timeline({ a, b, overlap, codes }) {
  const rows = [a, b].filter(Boolean).map((p) => ({
    p,
    start: parseDate(p.start_date),
    end: parseDate(p.in_service),
    color: utilityColor(p.utility, codes),
  }));
  const dates = rows.flatMap((r) => [r.start, r.end]).filter(Boolean);
  if (!dates.length) return null;

  const minYear = Math.min(...dates.map((d) => d.getFullYear()));
  const maxYear = Math.max(...dates.map((d) => d.getFullYear())) + 1;
  const span = new Date(maxYear, 0, 1) - new Date(minYear, 0, 1);
  const pct = (d) => ((d - new Date(minYear, 0, 1)) / span) * 100;
  const years = [];
  for (let y = minYear; y <= maxYear; y++) years.push(y);

  const verdict = overlap.time_overlap
    ? "Built in the same window: crews and equipment can be shared at the same time."
    : overlap.time_gap_days != null
    ? `In service ${Math.round(overlap.time_gap_days / 30.4)} months apart: coordinate sequencing and reuse of staging areas.`
    : "Schedule unknown for one of the projects.";

  return (
    <div className="timeline">
      <div className="timeline-title">When construction happens</div>
      {rows.map(({ p, start, end, color }) => (
        <div className="timeline-row" key={p.id}>
          <span className="timeline-label" style={{ color }}>{p.utility}</span>
          <div className="timeline-track">
            {start && end && (
              <div
                className="timeline-bar"
                style={{ left: `${pct(start)}%`, width: `${Math.max(pct(end) - pct(start), 1.5)}%`, background: color }}
              />
            )}
            {end && (
              <div className="timeline-diamond" style={{ left: `${pct(end)}%`, background: color }} />
            )}
          </div>
          <span className="timeline-date">
            {start ? `${fmtMonth(p.start_date)} → ` : ""}
            {fmtMonth(p.in_service)}
          </span>
        </div>
      ))}
      <div className="timeline-axis">
        {years.map((y) => (
          <span key={y} style={{ left: `${((new Date(y, 0, 1) - new Date(minYear, 0, 1)) / span) * 100}%` }}>
            {y}
          </span>
        ))}
      </div>
      <div className={overlap.time_overlap ? "timeline-verdict same" : "timeline-verdict"}>{verdict}</div>
    </div>
  );
}
