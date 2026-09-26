import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.REACT_APP_API_BASE || "http://localhost:8000";
const STATES = ["SC", "GA", "NC", "FL", "AL", "TN", "VA"];

// Upload a utility's planning PDF. The backend parses it (regex for known layouts,
// Gemini for new ones), matches substations and recomputes overlaps; we poll for progress.
export default function Upload({ onDone }) {
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [state, setState] = useState("SC");
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [utilities, setUtilities] = useState([]);
  const timer = useRef(null);

  const loadUtilities = () =>
    fetch(`${API_BASE}/api/utilities`)
      .then((r) => r.json())
      .then(setUtilities)
      .catch(() => {});

  useEffect(() => {
    loadUtilities();
    return () => clearInterval(timer.current);
  }, []);

  async function remove(code) {
    const res = await fetch(`${API_BASE}/api/utilities/${code}`, { method: "DELETE" });
    if (res.ok) {
      setUtilities(await res.json());
      if (onDone) onDone();
    }
  }

  const busy = job && !["done", "error"].includes(job.status);

  function poll(jobId) {
    clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/upload/${jobId}`);
        const j = await res.json();
        setJob(j);
        if (j.status === "done" || j.status === "error") {
          clearInterval(timer.current);
          if (j.status === "done") {
            loadUtilities();
            if (onDone) onDone(j.result);
          }
        }
      } catch (err) {
        clearInterval(timer.current);
        setError(err.message);
      }
    }, 1000);
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setJob(null);
    const form = new FormData();
    form.append("file", file);
    form.append("utility_name", name);
    form.append("state", state);
    try {
      const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Upload failed");
      setJob(body);
      poll(body.job_id);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="upload-panel" onSubmit={submit}>
      <input
        type="file"
        accept="application/pdf"
        onChange={(e) => setFile(e.target.files[0] || null)}
      />
      <input
        type="text"
        placeholder="Utility company name (e.g. Duke Energy Carolinas)"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <select value={state} onChange={(e) => setState(e.target.value)}>
        {STATES.map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
      <button type="submit" disabled={!file || !name.trim() || busy}>
        {busy ? "Processing…" : "Upload plan"}
      </button>

      {job && job.status !== "error" && (
        <div className="upload-progress">
          <progress max="100" value={job.progress} />
          <span>
            {job.status === "done"
              ? `${job.result.utility}: ${job.result.count} projects, ${job.result.located} located, ` +
                `${job.result.overlaps} overlaps with other utilities`
              : job.message}
          </span>
        </div>
      )}
      {job?.note && <div className="upload-note">{job.note}</div>}
      {(error || job?.status === "error") && (
        <div className="upload-error">{error || job.message}</div>
      )}
      <div className="utility-chips">
        <span className="chips-label">Loaded:</span>
        {utilities.map((u) => (
          <span key={u.code} className="utility-chip" title={`${u.name} (${u.state})`}>
            <b>{u.code}</b> {u.projects} projects
            {!u.preloaded && (
              <button type="button" onClick={() => remove(u.code)} title="Remove this upload">
                ×
              </button>
            )}
          </span>
        ))}
      </div>
    </form>
  );
}
