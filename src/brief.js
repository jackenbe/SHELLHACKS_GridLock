import { useState } from "react";
import { API_BASE } from "./api";

// "Draft coordination memo": Gemini writes it from GridTalk's data; the backend checks every
// number against that data and falls back to a fact-only template if anything doesn't match.
export default function Brief({ rank }) {
  const [state, setState] = useState({ loading: false, result: null, error: null });
  const [copied, setCopied] = useState(false);

  async function draft() {
    setState({ loading: true, result: null, error: null });
    try {
      const res = await fetch(`${API_BASE}/api/overlaps/${rank}/brief`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Could not draft the memo");
      setState({ loading: false, result: body, error: null });
    } catch (err) {
      setState({ loading: false, result: null, error: err.message });
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(state.result.memo);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  }

  const r = state.result;
  return (
    <div className="detail-card brief">
      <div className="detail-title">Coordination memo</div>
      {!r && (
        <button type="button" className="btn btn-primary wide" onClick={draft} disabled={state.loading}>
          {state.loading ? "Drafting…" : "Draft coordination memo"}
        </button>
      )}
      {state.error && <div className="upload-error">{state.error}</div>}
      {r && (
        <>
          <div className="brief-meta">
            <span className={r.source === "gemini" ? "brief-badge ai" : "brief-badge"}>
              {r.source === "gemini" ? "Drafted by Gemini · every number checked" : "Fact-only template"}
            </span>
            <button type="button" className="btn btn-small" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
          </div>
          {r.note && <div className="brief-note">{r.note}</div>}
          <pre className="brief-text">{r.memo}</pre>
        </>
      )}
    </div>
  );
}
