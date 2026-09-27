import { useEffect, useRef, useState } from "react";

import { API_BASE } from "./api";
const STATES = ["SC", "GA", "NC", "FL", "AL", "TN", "VA"];

// "Add a utility" sheet. Two ways in: find the utility's planning PDFs online, or upload one.
// Either way the backend parses it (regex for known layouts, Gemini for new ones), matches
// substations and recomputes overlaps; we poll the job for progress.
export default function Upload({ onDone, onClose }) {
  const [mode, setMode] = useState("find");
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [state, setState] = useState("SC");
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [found, setFound] = useState(null);
  const [searching, setSearching] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearInterval(timer.current), []);

  const busy = job && !["done", "error"].includes(job.status);

  function poll(jobId) {
    clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const j = await (await fetch(`${API_BASE}/api/upload/${jobId}`)).json();
        setJob(j);
        if (j.status === "done" || j.status === "error") {
          clearInterval(timer.current);
          if (j.status === "done" && onDone) onDone(j.result);
        }
      } catch (err) {
        clearInterval(timer.current);
        setError(err.message);
      }
    }, 1000);
  }

  async function post(path, body, json = true) {
    const res = await fetch(`${API_BASE}${path}`, json
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : { method: "POST", body });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || "Request failed");
    return out;
  }

  async function findPlans() {
    setError(null);
    setFound(null);
    setSearching(true);
    try {
      setFound(await post("/api/find-plans", { utility_name: name, state }));
    } catch (err) {
      setError(err.message);
    } finally {
      setSearching(false);
    }
  }

  async function importUrl(url, knownState) {
    setError(null);
    setJob(null);
    // the finder knows where some utilities are (e.g. FPL -> FL); that beats the dropdown
    const st = knownState || state;
    if (knownState) setState(knownState);
    try {
      const j = await post("/api/import-url", { url, utility_name: name, state: st });
      setJob(j);
      poll(j.job_id);
    } catch (err) {
      setError(err.message);
    }
  }

  async function upload(e) {
    e.preventDefault();
    setError(null);
    setJob(null);
    const form = new FormData();
    form.append("file", file);
    form.append("utility_name", name);
    form.append("state", state);
    try {
      const j = await post("/api/upload", form, false);
      setJob(j);
      poll(j.job_id);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="add-utility" onSubmit={upload}>
      <div className="sheet-head">
        <div>
          <h2>Add a utility</h2>
          <p className="muted">
            Its planned projects are read from the filing, placed on the map, and compared with every
            utility already loaded.
          </p>
        </div>
        {onClose && (
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        )}
      </div>

      <div className="field-row">
        <label className="field grow">
          <span>Utility</span>
          <input
            type="text"
            placeholder="Utility company name (e.g. Duke Energy Carolinas)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </label>
        <label className="field">
          <span>State</span>
          <select value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="segmented" role="tablist">
        <button type="button" className={mode === "find" ? "on" : ""} onClick={() => setMode("find")}>
          Find online
        </button>
        <button type="button" className={mode === "upload" ? "on" : ""} onClick={() => setMode("upload")}>
          Upload PDF
        </button>
      </div>

      {mode === "find" ? (
        <>
          <button type="button" className="btn btn-primary wide" onClick={findPlans}
            disabled={!name.trim() || searching || busy}>
            {searching ? "Searching planning portals…" : "Find plans online"}
          </button>
          {found && (
            <div className="found-list">
              {found.candidates.length === 0 ? (
                <div className="found-empty">
                  No plan PDFs found for "{name}".
                  {!found.used_gemini && " Add GEMINI_API_KEY to search the whole web, not just known planning portals."}
                  {found.errors && found.errors.length > 0 && (
                    <div className="upload-error">{found.errors.join(" · ")}</div>
                  )}
                </div>
              ) : (
                found.candidates.map((c) => (
                  <div key={c.url} className={c.verified ? "found-item" : "found-item unverified"}>
                    <div className="found-main">
                      <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a>
                      <span className="found-meta">
                        {c.source}
                        {c.state ? ` · ${c.state}` : ""}
                        {c.size_mb ? ` · ${c.size_mb} MB` : ""}
                        {c.verified ? " · PDF confirmed" : " · couldn't confirm it's a PDF"}
                      </span>
                    </div>
                    <button type="button" className="btn btn-small" onClick={() => importUrl(c.url, c.state)}
                      disabled={busy}>
                      Import
                    </button>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <label className={file ? "dropzone has-file" : "dropzone"}>
            <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files[0] || null)} />
            <span className="drop-title">{file ? file.name : "Choose a planning PDF"}</span>
            <span className="muted">
              {file ? `${(file.size / 1e6).toFixed(1)} MB` : "Transmission plan, IRP appendix or project list · up to 60 MB"}
            </span>
          </label>
          <button type="submit" className="btn btn-primary wide" disabled={!file || !name.trim() || busy}>
            {busy ? "Processing…" : "Upload plan"}
          </button>
        </>
      )}

      {job && job.status !== "error" && (
        <div className="progress">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${job.progress || 0}%` }} />
          </div>
          <div className="progress-text">
            {job.status === "done" ? (
              <>
                <b>{job.result.utility}</b> · {job.result.count} projects · {job.result.located} located ·{" "}
                {job.result.overlaps} overlaps with other utilities
              </>
            ) : (
              <>
                <span className="mono">{job.progress || 0}%</span> {job.message}
              </>
            )}
          </div>
        </div>
      )}
      {job?.note && <div className="upload-note">{job.note}</div>}
      {(error || job?.status === "error") && <div className="upload-error">{error || job.message}</div>}
    </form>
  );
}
