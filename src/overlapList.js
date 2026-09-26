import { useState } from "react";
import { TIER_COLORS, utilityColor } from "./colors";
import { ImpactChip, ImpactDetail, ImpactSummary } from "./impact";
import { fmtYear } from "./dates";
import Timeline from "./timeline";

// Ranked list of coordination opportunities. Click one to zoom the map to that pair.
export default function OverlapList({ overlaps, projectsById, codes, selectedRank, onSelect, impact }) {
  const [sortBy, setSortBy] = useState("distance");
  const saving = (o) => (o.impact ? o.impact.savings_if_aligned : 0);
  const shown = sortBy === "money" ? [...overlaps].sort((x, y) => saving(y) - saving(x)) : overlaps;

  return (
    <aside className="overlap-list">
      <h2>Top coordination opportunities</h2>
      <ImpactSummary summary={impact} />
      <p className="overlap-count">
        {overlaps.length} project pairs within 25 mi. Click one to see it on the map.
      </p>
      <div className="sort-toggle">
        Sort by:
        <button className={sortBy === "distance" ? "on" : ""} onClick={() => setSortBy("distance")}>
          closest
        </button>
        <button className={sortBy === "money" ? "on" : ""} onClick={() => setSortBy("money")}>
          most savings
        </button>
      </div>

      {overlaps.length === 0 && <p>No overlaps found.</p>}

      <ol>
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
              <div className="overlap-head">
                <span className="overlap-rank">#{o.rank}</span>
                <span className="tier-chip" style={{ background: TIER_COLORS[o.tier] }}>
                  {o.tier}
                </span>
                {o.time_overlap && <span className="time-chip">same build window</span>}
                <ImpactChip impact={o.impact} />
                <span className="overlap-dist">
                  {o.distance_km === 0 ? "touching" : `${o.distance_mi} mi`}
                </span>
              </div>
              {[[o.utility_a, o.name_a, a], [o.utility_b, o.name_b, b]].map(([code, name, p]) => (
                <div className="overlap-project" key={code + name}>
                  <span className="dot" style={{ background: utilityColor(code, codes) }} />
                  <b>{code}</b> {name}
                  <span className="overlap-year">{p ? fmtYear(p.in_service) : ""}</span>
                </div>
              ))}
              {selected && (
                <div className="overlap-detail" onClick={(e) => e.stopPropagation()}>
                  <p>{o.tier_info}</p>
                  <Timeline a={a} b={b} overlap={o} codes={codes} />
                  <ImpactDetail impact={o.impact} o={o} />
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
