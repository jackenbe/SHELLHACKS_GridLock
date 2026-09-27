import { useState } from "react";
import { TIER_STYLES, utilityColor } from "./colors";
import { fmtYear } from "./dates";
import { ImpactChip, ImpactDetail, ImpactSummary } from "./impact";
import Timeline from "./timeline";

function TierPill({ tier }) {
  const t = TIER_STYLES[tier] || { bg: "#E5E5EA", fg: "#1d1d1f", label: tier };
  return <span className="tier-chip" style={{ background: t.bg, color: t.fg }}>{t.label}</span>;
}

// Ranked list of coordination opportunities. Click one to fly the map to that pair.
export default function OverlapList({ overlaps, projectsById, codes, selectedRank, onSelect, impact }) {
  const [sortBy, setSortBy] = useState("distance");
  const saving = (o) => (o.impact ? o.impact.savings_if_aligned : 0);
  const shown = sortBy === "money" ? [...overlaps].sort((x, y) => saving(y) - saving(x)) : overlaps;

  return (
    <div className="overlap-list">
      <div className="list-head">
        <h1>Coordination opportunities</h1>
        <p className="muted">
          <span className="mono">{overlaps.length}</span> cross-utility project pairs within 25 mi
        </p>
      </div>

      <ImpactSummary summary={impact} />

      <div className="segmented" role="tablist" aria-label="Sort">
        <button className={sortBy === "distance" ? "on" : ""} onClick={() => setSortBy("distance")}>
          Closest
        </button>
        <button className={sortBy === "money" ? "on" : ""} onClick={() => setSortBy("money")}>
          Most savings
        </button>
      </div>

      {overlaps.length === 0 && <p className="muted empty">No overlaps between the loaded utilities.</p>}

      <ol className="rows">
        {shown.map((o) => {
          const selected = o.rank === selectedRank;
          const a = projectsById[o.id_a];
          const b = projectsById[o.id_b];
          return (
            <li
              key={o.rank}
              className={selected ? "overlap-item selected" : "overlap-item"}
              onClick={() => onSelect(selected ? null : o.rank)}
            >
              <div className="row-top">
                <span className="overlap-rank mono">{String(o.rank).padStart(2, "0")}</span>
                <TierPill tier={o.tier} />
                {o.time_overlap && <span className="time-chip">Same window</span>}
                <ImpactChip impact={o.impact} />
                <span className="overlap-dist mono">
                  {o.distance_km === 0 ? "0.0 mi" : `${o.distance_mi} mi`}
                </span>
              </div>
              {[[o.utility_a, o.name_a, a], [o.utility_b, o.name_b, b]].map(([code, name, p]) => (
                <div className="overlap-project" key={code + name}>
                  <span className="dot" style={{ background: utilityColor(code, codes) }} />
                  <span className="code mono">{code}</span>
                  <span className="pname">{name}</span>
                  <span className="overlap-year mono">{p ? fmtYear(p.in_service) : ""}</span>
                </div>
              ))}
              {selected && (
                <div className="overlap-detail" onClick={(e) => e.stopPropagation()}>
                  <p className="tier-info">{o.tier_info}</p>
                  <Timeline a={a} b={b} overlap={o} codes={codes} />
                  <ImpactDetail impact={o.impact} o={o} />
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
