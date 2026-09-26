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
