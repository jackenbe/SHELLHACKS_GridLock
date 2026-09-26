// Money and resources saved by coordinating (= wasted when planned separately).
export function money(musd) {
  if (musd == null) return "?";
  if (musd === 0) return "$0";
  if (musd >= 1) return `$${musd.toFixed(1)}M`;
  return `$${Math.round(musd * 1000)}K`;
}

export function ImpactSummary({ summary }) {
  if (!summary) return null;
  const now = summary.current_schedules;
  const aligned = summary.if_schedules_aligned;
  return (
    <div className="impact-summary">
      <div className="impact-title">Money at stake</div>
      <div className="impact-numbers">
        <div>
          <span className="impact-big">{money(now.savings_musd)}</span>
          <span className="impact-sub">saved with today's schedules</span>
        </div>
        <div>
          <span className="impact-big aligned">{money(aligned.savings_musd)}</span>
          <span className="impact-sub">if overlapping schedules are aligned</span>
        </div>
      </div>
      <div className="impact-resources">
        {aligned.mobilizations_avoided} crew mobilizations · {aligned.studies_avoided} environmental
        studies{aligned.row_acres_shared ? ` · ${aligned.row_acres_shared} acres of right-of-way` : ""} not
        duplicated
      </div>
      <details className="impact-how">
        <summary>How is this estimated?</summary>
        <p>{summary.note}</p>
        <ul>
          {summary.assumptions.map((a) => (
            <li key={a.item}>
              <b>{a.item}:</b> {a.value} <span className="impact-source">({a.source})</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function ImpactChip({ impact }) {
  if (!impact) return null;
  if (impact.savings > 0) return <span className="money-chip">saves {money(impact.savings)}</span>;
  if (impact.savings_if_aligned > 0)
    return <span className="money-chip aligned">up to {money(impact.savings_if_aligned)}</span>;
  return null;
}

export function ImpactDetail({ impact, o }) {
  if (!impact) return null;
  return (
    <div className="impact-detail">
      <div className="timeline-title">Money and resources</div>
      <table>
        <tbody>
          <tr>
            <td>{o.utility_a} project cost</td>
            <td className="num">{money(impact.cost_a)}</td>
            <td className="basis">{impact.cost_a_basis}</td>
          </tr>
          <tr>
            <td>{o.utility_b} project cost</td>
            <td className="num">{money(impact.cost_b)}</td>
            <td className="basis">{impact.cost_b_basis}</td>
          </tr>
          {impact.items.map((i) => (
            <tr key={i.key} className={i.needs_alignment ? "needs-align" : "saving"}>
              <td>{i.label}</td>
              <td className="num">{money(i.amount)}</td>
              <td className="basis">{i.detail}</td>
            </tr>
          ))}
          <tr className="impact-total">
            <td>Saved if coordinated</td>
            <td className="num">
              {money(impact.savings)}
              {impact.savings_if_aligned > impact.savings && (
                <> (up to {money(impact.savings_if_aligned)})</>
              )}
            </td>
            <td />
          </tr>
        </tbody>
      </table>
      {impact.resources.length > 0 && (
        <ul className="impact-list">
          {impact.resources.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
