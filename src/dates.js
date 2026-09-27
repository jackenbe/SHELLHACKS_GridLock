// Utility PDFs use "12/31/23", "06/01/2025" or ISO "2025-06-01".
export function parseDate(value) {
  if (!value) return null;
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
  m = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec(value.trim());
  if (!m) return null;
  let year = +m[3];
  if (year < 100) year += 2000;
  return new Date(year, +m[1] - 1, +m[2]);
}

export function fmtMonth(value) {
  const d = parseDate(value);
  return d ? d.toLocaleDateString("en-US", { month: "short", year: "numeric" }) : "date unknown";
}

export function fmtYear(value) {
  const d = parseDate(value);
  return d ? String(d.getFullYear()) : "?";
}

// Build window used by the timeline: [start, in-service]. When a filing gives no start date,
// construction is assumed to take the 12 months before in-service, the same rule the
// overlap engine uses for its "same build window" check.
const YEAR_MS = 365 * 24 * 3600 * 1000;

export function buildWindow(p) {
  const end = parseDate(p.in_service);
  if (!end) return null;
  const start = parseDate(p.start_date) || new Date(end.getTime() - YEAR_MS);
  return [start, end];
}

export function activeInYear(p, year) {
  const w = buildWindow(p);
  return !!w && w[0] <= new Date(year, 11, 31) && w[1] >= new Date(year, 0, 1);
}
