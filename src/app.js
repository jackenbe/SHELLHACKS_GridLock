import { useEffect, useMemo, useState } from "react";
import "./styles.css";
import Map from "./map";
import OverlapList from "./overlapList";
import Upload from "./upload";

const API_BASE = process.env.REACT_APP_API_BASE || "http://localhost:8000";

export default function App() {
  const [projects, setProjects] = useState([]);
  const [overlaps, setOverlaps] = useState([]);
  const [impact, setImpact] = useState(null);
  const [selectedRank, setSelectedRank] = useState(null);
  const [dataVersion, setDataVersion] = useState(0); // bumped after an upload -> refetch
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/api/projects`).then((r) => r.json()),
      fetch(`${API_BASE}/api/overlaps`).then((r) => r.json()),
      fetch(`${API_BASE}/api/impact`).then((r) => r.json()),
    ])
      .then(([proj, ov, imp]) => {
        setProjects(proj);
        setOverlaps(ov);
        setImpact(imp);
        setSelectedRank(null);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [dataVersion]);

  const codes = useMemo(() => [...new Set(projects.map((p) => p.utility))], [projects]);
  const selected = overlaps.find((o) => o.rank === selectedRank) || null;
  const projectsById = useMemo(() => Object.fromEntries(projects.map((p) => [p.id, p])), [projects]);

  return (
    <>
      <Upload onDone={() => setDataVersion((v) => v + 1)} />
      {loading && <div className="map-status">Loading projects…</div>}
      {error && <div className="map-status">Failed to load: {error}</div>}
      {!loading && !error && (
        <div className="main">
          <OverlapList
            overlaps={overlaps}
            projectsById={projectsById}
            impact={impact}
            codes={codes}
            selectedRank={selectedRank}
            onSelect={setSelectedRank}
          />
          <Map projects={projects} overlaps={overlaps} codes={codes} selected={selected} />
        </div>
      )}
    </>
  );
}
