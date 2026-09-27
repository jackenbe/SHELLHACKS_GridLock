import { useCallback, useEffect, useMemo, useState } from "react";
import "./styles.css";
import { utilityColor } from "./colors";
import { activeInYear, buildWindow } from "./dates";
import Map from "./map";
import OverlapList from "./overlapList";
import TimeSlider from "./timeSlider";
import Upload from "./upload";

import { API_BASE } from "./api";

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="currentColor" />
      <path d="M7 22 L14 12 L19 18 L25 9" fill="none" stroke="#fff" strokeWidth="2.4"
        strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="14" cy="12" r="2.2" fill="#fff" />
      <circle cx="19" cy="18" r="2.2" fill="#fff" />
    </svg>
  );
}

function Skeleton() {
  return (
    <div className="skeleton">
      <div className="sk sk-title" />
      <div className="sk sk-card" />
      <div className="sk sk-row" />
      <div className="sk sk-row" />
      <div className="sk sk-row" />
    </div>
  );
}

export default function App() {
  const [data, setData] = useState({ projects: [], overlaps: [], impact: null, utilities: [] });
  const [selectedRank, setSelectedRank] = useState(null);
  const [dataVersion, setDataVersion] = useState(0); // bumped after an upload/removal -> refetch
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [error, setError] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [year, setYear] = useState(null); // timeline: null = show every project

  useEffect(() => {
    setLoading(true);
    const get = (path) =>
      fetch(`${API_BASE}${path}`).then((r) => {
        if (!r.ok) throw new Error(`${path} returned ${r.status}`);
        return r.json();
      });
    Promise.all([get("/api/projects"), get("/api/overlaps"), get("/api/impact"), get("/api/utilities")])
      .then(([projects, overlaps, impact, utilities]) => {
        setData({ projects, overlaps, impact, utilities });
        setSelectedRank(null);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [dataVersion]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && (sheetOpen ? setSheetOpen(false) : setSelectedRank(null));
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sheetOpen]);

  const refresh = useCallback(() => setDataVersion((v) => v + 1), []);
  const { projects, overlaps, impact, utilities } = data;
  const codes = useMemo(
    () => [...new Set([...utilities.map((u) => u.code), ...projects.map((p) => p.utility)])],
    [projects, utilities]
  );
  const projectsById = useMemo(() => Object.fromEntries(projects.map((p) => [p.id, p])), [projects]);
  const selected = overlaps.find((o) => o.rank === selectedRank) || null;
  const located = projects.filter((p) => p.located).length;

  // timeline: which projects are under construction in the chosen year
  const yearRange = useMemo(() => {
    const ws = projects.filter((p) => p.located).map(buildWindow).filter(Boolean);
    if (!ws.length) return [null, null];
    return [Math.min(...ws.map((w) => w[0].getFullYear())), Math.max(...ws.map((w) => w[1].getFullYear()))];
  }, [projects]);
  const activeIds = useMemo(
    () => (year == null ? null : new Set(projects.filter((p) => activeInYear(p, year)).map((p) => p.id))),
    [projects, year]
  );
  const activePairs = useMemo(
    () => (activeIds ? overlaps.filter((o) => activeIds.has(o.id_a) && activeIds.has(o.id_b)) : []),
    [overlaps, activeIds]
  );
  const buildingCount = activeIds ? projects.filter((p) => p.located && activeIds.has(p.id)).length : 0;

  async function removeUtility(code) {
    const res = await fetch(`${API_BASE}/api/utilities/${code}`, { method: "DELETE" });
    if (res.ok) refresh();
  }

  return (
    <div className={sidebarOpen ? "app" : "app sidebar-closed"}>
      <Map projects={projects} overlaps={overlaps} codes={codes} selected={selected}
        activeIds={activeIds} activePairs={activePairs} sidebarOpen={sidebarOpen} />

      <TimeSlider range={yearRange} year={year} onYear={setYear} timeline={impact?.timeline}
        stats={{ building: buildingCount, pairs: activePairs.length }} />

      <header className="topbar glass">
        <button type="button" className="icon-btn sidebar-toggle" onClick={() => setSidebarOpen((o) => !o)}
          aria-label={sidebarOpen ? "Hide list" : "Show list"} aria-expanded={sidebarOpen}
          aria-controls="overlap-sidebar" title={sidebarOpen ? "Hide list" : "Show list"}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="3" />
            <line x1="9" y1="4" x2="9" y2="20" />
            {sidebarOpen && <rect x="3.9" y="4.9" width="4.2" height="14.2" rx="2" fill="currentColor" stroke="none" />}
          </svg>
        </button>
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">GridTalk</div>
            <div className="brand-sub">Transmission coordination</div>
          </div>
        </div>

        <div className="status mono" title="Projects located on the map / all parsed projects">
          <span className={error ? "live-dot off" : loading ? "live-dot busy" : "live-dot"} />
          {error ? "Offline" : loading ? "Syncing" : `${located}/${projects.length} located · ${overlaps.length} overlaps`}
        </div>

        <div className="utility-chips">
          {utilities.map((u) => (
            <span key={u.code} className="utility-chip" title={`${u.name} (${u.state})`}>
              <span className="dot" style={{ background: utilityColor(u.code, codes) }} />
              <b>{u.code}</b>
              <span className="mono muted">{u.projects}</span>
              {!u.preloaded && (
                <button type="button" onClick={() => removeUtility(u.code)} aria-label={`Remove ${u.name}`}
                  title="Remove this upload">
                  ×
                </button>
              )}
            </span>
          ))}
        </div>

        <button className="btn btn-primary" onClick={() => setSheetOpen(true)}>
          <span aria-hidden="true">＋</span> Add utility
        </button>
      </header>

      <aside id="overlap-sidebar" className={sidebarOpen ? "sidebar glass" : "sidebar glass collapsed"}
        aria-hidden={!sidebarOpen} inert={sidebarOpen ? undefined : ""}>
        {error ? (
          <div className="state-msg">
            <h3>Can't reach the GridTalk API</h3>
            <p className="muted">{error}</p>
            <button className="btn" onClick={refresh}>Try again</button>
          </div>
        ) : loading && !projects.length ? (
          <Skeleton />
        ) : (
          <OverlapList
            overlaps={overlaps}
            projectsById={projectsById}
            impact={impact}
            codes={codes}
            selectedRank={selectedRank}
            onSelect={setSelectedRank}
          />
        )}
      </aside>

      {sheetOpen && (
        <div className="sheet-backdrop" onClick={() => setSheetOpen(false)}>
          <div className="sheet glass" role="dialog" aria-label="Add a utility" onClick={(e) => e.stopPropagation()}>
            <Upload onDone={refresh} onClose={() => setSheetOpen(false)} />
          </div>
        </div>
      )}
    </div>
  );
}
