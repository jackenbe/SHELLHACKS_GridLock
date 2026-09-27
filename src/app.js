import { useCallback, useEffect, useMemo, useState } from "react";
import "./styles.css";
import { utilityColor } from "./colors";
import Map from "./map";
import OverlapList from "./overlapList";
import Upload from "./upload";

const API_BASE = process.env.REACT_APP_API_BASE ?? "http://localhost:8000";

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
  const [error, setError] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);

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

  async function removeUtility(code) {
    const res = await fetch(`${API_BASE}/api/utilities/${code}`, { method: "DELETE" });
    if (res.ok) refresh();
  }

  return (
    <div className="app">
      <Map projects={projects} overlaps={overlaps} codes={codes} selected={selected} />

      <header className="topbar glass">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">GridLock</div>
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

      <aside className="sidebar glass">
        {error ? (
          <div className="state-msg">
            <h3>Can't reach the GridLock API</h3>
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
