// One place for the backend address. Empty string (production build) = same site.
export const API_BASE = process.env.REACT_APP_API_BASE ?? "http://localhost:8000";

// The utility's original filing, opened at the page the project was read from.
export function sourceUrl(p) {
  return `${API_BASE}/api/source/${encodeURIComponent(p.utility)}${p.page ? `#page=${p.page}` : ""}`;
}
