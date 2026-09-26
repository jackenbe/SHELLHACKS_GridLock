// Shared colors so the map, list and legend always match.
export const UTILITY_COLORS = {
  DESC: "#2563eb", // Dominion Energy South Carolina: blue
  GPC: "#ea580c",  // Georgia Power: orange
};
const EXTRA = ["#16a34a", "#9333ea", "#0891b2", "#be185d"]; // uploaded utilities

export function utilityColor(code, allCodes = []) {
  if (UTILITY_COLORS[code]) return UTILITY_COLORS[code];
  const others = allCodes.filter((c) => !UTILITY_COLORS[c]).sort();
  return EXTRA[Math.max(0, others.indexOf(code)) % EXTRA.length];
}

export const TIER_COLORS = {
  touching: "#dc2626",
  "right-of-way": "#f97316",
  "site logistics": "#eab308",
  crews: "#64748b",
};

export const SELECTED_COLOR = "#dc2626";
