import { useEffect, useRef, useState } from "react";

// Scrub or play through the years: the map shows only projects under construction that year,
// and pulses overlapping pairs that are both being built at the same time.
export default function TimeSlider({ range, year, onYear, stats }) {
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
        <input type="range" min={min} max={max} step={1} value={year}
          onChange={(e) => { setPlaying(false); onYear(Number(e.target.value)); }} aria-label="Year" />
        <div className="ts-note">
          No start date in a filing: construction assumed to take the 12 months before in-service
          (same rule as the overlap engine).
        </div>
      </div>
      <button className="icon-btn" onClick={() => { setPlaying(false); onYear(null); }} aria-label="Close timeline">×</button>
    </div>
  );
}
