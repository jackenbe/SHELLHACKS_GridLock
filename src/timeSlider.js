import { useEffect, useRef, useState } from "react";
import { money } from "./impact";

// Running total of coordination savings lost by each year if the utilities keep planning
// separately. The backend books each pair's savings in the in-service year of its later
// project (once both are built on their own), using the same no-double-counting shares
// as the totals, so the curves end at the sidebar totals.
function lostByYear(timeline, min, max) {
  const rows = timeline?.by_year || [];
  const out = [];
  let today = 0;
  let aligned = 0;
  for (let y = min; y <= max; y += 1) {
    rows.filter((r) => r.year === y).forEach((r) => { today += r.today_musd; aligned += r.aligned_musd; });
    out.push({ year: y, today, aligned });
  }
  return out;
}

function stepPath(series, key, x, yOf) {
  return series.map((d, i) => (i === 0 ? `M${x(d.year)},${yOf(d[key])}` : `H${x(d.year)}V${yOf(d[key])}`)).join("");
}

function WasteChart({ series, year, min, max }) {
  const W = 100;
  const H = 30;
  const top = Math.max(...series.map((d) => Math.max(d.today, d.aligned)), 0.001);
  const x = (y) => (max === min ? 0 : ((y - min) / (max - min)) * W);
  const yOf = (v) => H - 1.5 - (v / top) * (H - 4);
  const aligned = stepPath(series, "aligned", x, yOf);
  return (
    <svg className="ts-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={`${aligned}H${W}V${H}H0Z`} className="ts-area" />
      <path d={aligned} className="ts-line aligned" />
      <path d={stepPath(series, "today", x, yOf)} className="ts-line today" />
      <line x1={x(year)} x2={x(year)} y1="0" y2={H} className="ts-marker" />
    </svg>
  );
}

// Scrub or play through the years: the map shows only projects under construction that year,
// and pulses overlapping pairs that are both being built at the same time.
export default function TimeSlider({ range, year, onYear, stats, timeline }) {
  const [playing, setPlaying] = useState(false);
  const timer = useRef(null);
  const [min, max] = range;

  useEffect(() => {
    if (!playing) return undefined;
    timer.current = setInterval(() => {
      onYear((y) => {
        if (y >= max) {
          setPlaying(false);
          return y;
        }
        return y + 1;
      });
    }, 1100);
    return () => clearInterval(timer.current);
  }, [playing, max, onYear]);

  if (year == null) {
    return (
      <button className="timeline-toggle glass" onClick={() => onYear(min)} disabled={min == null}>
        <span aria-hidden="true">◷</span> Timeline
      </button>
    );
  }

  const series = timeline?.by_year?.length ? lostByYear(timeline, min, max) : null;
  const now = series?.find((d) => d.year === year);
  const end = series?.[series.length - 1];

  function togglePlay() {
    if (!playing && year >= max) onYear(min);
    setPlaying((p) => !p);
  }

  return (
    <div className="time-slider glass">
      <button className="play-btn" onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
        {playing ? "❚❚" : "▶"}
      </button>
      <div className="ts-main">
        <div className="ts-top">
          <span className="ts-year mono">{year}</span>
          <span className="ts-stats">
            <b className="mono">{stats.building}</b> projects under construction ·{" "}
            <b className="mono">{stats.pairs}</b> overlapping pairs building at the same time
          </span>
        </div>
        {series && now && (
          <div className="ts-waste" title="Savings count as lost in the year the later project of a pair goes into service">
            <span className="muted">Lost by {year} if planned separately:</span>{" "}
            <b className="mono today">{money(now.today)}</b> with today's schedules ·{" "}
            <b className="mono aligned">{money(now.aligned)}</b> if aligned
            <span className="muted"> (of {money(end.aligned)})</span>
          </div>
        )}
        {series && <WasteChart series={series} year={year} min={min} max={max} />}
        <input type="range" min={min} max={max} step={1} value={year}
          onChange={(e) => { setPlaying(false); onYear(Number(e.target.value)); }} aria-label="Year" />
        <div className="ts-note">
          No start date in a filing: construction assumed to take the 12 months before in-service.
          {series && " Savings count as lost once the later project of a pair is in service."}
        </div>
      </div>
      <button className="icon-btn" onClick={() => { setPlaying(false); onYear(null); }} aria-label="Close timeline">×</button>
    </div>
  );
}
