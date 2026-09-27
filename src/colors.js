// Shared colors so the map, list and legend always match.
// Utility colors: a fixed categorical order, validated for lightness, contrast and
// color-blind separation on both the light and dark map surfaces. Never cycled: a 5th+
// utility is drawn in neutral gray and identified by its label.
export const UTILITY_COLORS = {
  DESC: "#0071E3", // Dominion Energy South Carolina
  GPC: "#D96B00",  // Georgia Power
};
const EXTRA = ["#8E44EC", "#1F9D55"]; // next uploaded utilities, in this order
export const OTHER_COLOR = "#8E8E93";

export function utilityColor(code, allCodes = []) {
  if (UTILITY_COLORS[code]) return UTILITY_COLORS[code];
  const others = allCodes.filter((c) => !UTILITY_COLORS[c]).sort();
  const i = others.indexOf(code);
  return i >= 0 && i < EXTRA.length ? EXTRA[i] : OTHER_COLOR;
}

// Distance tiers are a magnitude (how close), so they use ONE hue from dark to light:
// darker = closer = more to coordinate. Always shown with a text label too.
export const TIER_STYLES = {
  touching: { bg: "#B3131A", fg: "#FFFFFF", label: "Touching" },
  "right-of-way": { bg: "#D93A40", fg: "#FFFFFF", label: "Right-of-way" },
  "site logistics": { bg: "#F2A4A7", fg: "#5C0B0E", label: "Site logistics" },
  crews: { bg: "#FBDADB", fg: "#5C0B0E", label: "Crews" },
};
export const TIER_COLORS = Object.fromEntries(Object.entries(TIER_STYLES).map(([k, v]) => [k, v.bg]));
