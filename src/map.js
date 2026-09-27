import "leaflet/dist/leaflet.css";
import { memo, useEffect, useMemo, useState } from "react";
import L from "leaflet";
import {
  CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, ZoomControl, useMap,
} from "react-leaflet";
import { sourceUrl } from "./api";
import { utilityColor } from "./colors";
import { fmtMonth } from "./dates";

// Every located project is drawn in its utility's color:
//   both substations found -> a line between them (with a dot at each end); one found -> a dot.
// Thick = overlaps another utility's project. Hover anything for its name and in-service date.
// Selecting an overlap fades everything else, labels both projects, and draws a dashed line
// between their nearest points with the distance on it.

// Draw every line/dot on one <canvas> instead of hundreds of SVG elements: panning and
// zooming stay smooth. tolerance makes thin lines easy to hover and click.
const CANVAS = L.canvas({ padding: 0.5, tolerance: 6 });

// Snappier interaction than Leaflet's defaults (half-step zoom, faster wheel, short fly).
const MAP_OPTIONS = {
  renderer: CANVAS,
  preferCanvas: true,
  zoomSnap: 0.25,
  zoomDelta: 0.5,
  wheelPxPerZoomLevel: 45,   // default 60: less scrolling per zoom level
  wheelDebounceTime: 10,     // default 40 ms: react to the wheel sooner
  inertiaDeceleration: 2000, // default 3000: drags glide a little further
  worldCopyJump: false,
  zoomControl: false,        // re-added bottom-right, out of the way of the panels
};

function points(p) {
  const pts = [];
  if (p.lat_a != null && p.lon_a != null) pts.push([p.lat_a, p.lon_a]);
  if (p.lat_b != null && p.lon_b != null) pts.push([p.lat_b, p.lon_b]);
  return pts;
}

// the westernmost project of the selected pair gets its label on the left
function labelSide(pair, i) {
  const lon = (p) => {
    const pts = points(p);
    return pts.reduce((s, q) => s + q[1], 0) / pts.length;
  };
  if (pair.length < 2) return "right";
  return lon(pair[i]) <= lon(pair[1 - i]) ? "left" : "right";
}

function ZoomToSelection({ selectedProjects, selectionKey, sidebarOpen }) {
  const map = useMap();
  useEffect(() => {
    const pts = selectedProjects.flatMap(points);
    // keep the pair clear of the list panel on the left and the top bar
    const wide = window.innerWidth > 820 && sidebarOpen; // on phones the list is a bottom sheet instead
    const sheet = window.innerWidth <= 820 && sidebarOpen;
    if (pts.length) map.flyToBounds(pts, {
      paddingTopLeft: wide ? [460, 130] : [40, 130],
      paddingBottomRight: sheet ? [40, window.innerHeight * 0.5] : [90, 90],
      maxZoom: 11, duration: 0.6,
    });
    // only when the selection changes or the list opens/closes, not on every re-render
  }, [map, selectionKey, sidebarOpen]);
  return null;
}

function ProjectPopup({ p }) {
  return (
    <Popup>
      <strong>{p.name}</strong>
      <br />
      {p.utility_name} · ID {p.project_id}
      <br />
      {p.start_date ? `Construction ${fmtMonth(p.start_date)} → ` : "In service "}
      {fmtMonth(p.in_service)}
      <br />
      A: {p.match_a || p.endpoint_a || "?"} ({p.conf_a})
      {p.endpoint_b && (
        <>
          <br />
          B: {p.match_b || p.endpoint_b} ({p.conf_b})
        </>
      )}
      <br />
      <a href={sourceUrl(p)} target="_blank" rel="noreferrer">
        Open {p.utility} filing{p.page ? `, page ${p.page}` : ""} ↗
      </a>
    </Popup>
  );
}

const ProjectShape = memo(function ProjectShape({ p, color, selected, faded, overlapping, side = "top" }) {
  const pts = points(p);
  const opacity = faded ? 0.25 : 0.95;
  const label = (
    <Tooltip sticky={!selected} permanent={selected} direction={selected ? side : "top"}
      offset={selected ? (side === "left" ? [-12, 0] : [12, 0]) : [0, -6]}
      className={selected ? "project-label" : ""}>
      <b>{p.utility}</b> {selected && p.name.length > 42 ? `${p.name.slice(0, 40)}…` : p.name}
      <br />
      {p.start_date ? `Building ${fmtMonth(p.start_date)} → ${fmtMonth(p.in_service)}` : `In service ${fmtMonth(p.in_service)}`}
    </Tooltip>
  );

  if (pts.length === 2) {
    const weight = selected ? 7 : overlapping ? 4 : 2.5;
    return (
      <>
        {selected && (  // white casing so the selected pair pops off the map
          <Polyline positions={pts} pathOptions={{ color: "#fff", weight: weight + 5, opacity: 1 }} />
        )}
        <Polyline positions={pts} pathOptions={{ color, weight, opacity }}>
          {label}
          <ProjectPopup p={p} />
        </Polyline>
        {pts.map((pt, i) => (  // substation dots at the line's ends
          <CircleMarker
            key={i}
            center={pt}
            radius={selected ? 6 : 3}
            pathOptions={{ color: "#fff", weight: 1.5, fillColor: color, fillOpacity: faded ? 0.25 : 1, opacity }}
          />
        ))}
      </>
    );
  }
  return (
    <CircleMarker
      center={pts[0]}
      radius={selected ? 10 : overlapping ? 7 : 5}
      pathOptions={{ color: "#fff", weight: 2, fillColor: color, fillOpacity: faded ? 0.25 : 0.95, opacity }}
    >
      {label}
      <ProjectPopup p={p} />
    </CircleMarker>
  );
});

// Timeline mode: a ring that pulses on each overlapping pair being built in the same year.
function PulseHalo({ center }) {
  const [big, setBig] = useState(false);
  useEffect(() => {
    const t = setInterval(() => setBig((b) => !b), 650);
    return () => clearInterval(t);
  }, []);
  return (
    <CircleMarker center={center} radius={big ? 17 : 10} interactive={false}
      pathOptions={{ color: "#B3131A", weight: 2.5, fill: false, opacity: big ? 0.3 : 0.9 }} />
  );
}

function DistanceLine({ overlap }) {
  if (!overlap.closest_a || !overlap.closest_b) return null;
  const { distance_km: km, distance_mi: mi, closest_name_a: na, closest_name_b: nb } = overlap;
  const where = (name) => name || "mid-line";

  const title = km === 0 ? "Touching / crossing" : `Closest point: ${km} km · ${mi} mi apart`;
  const subtitle =
    km === 0
      ? na || nb ? `at ${na || nb}` : "the two lines cross here"
      : `${overlap.utility_a} ${where(na)}  ↔  ${overlap.utility_b} ${where(nb)}`;
  const label = (
    <Tooltip permanent direction="bottom" offset={[0, 26]} className="distance-label">
      <div>{title}</div>
      <div className="distance-sub">{subtitle}</div>
    </Tooltip>
  );
  // black rings mark the exact nearest point on each project
  const ring = (pos, key, withLabel) => (
    <CircleMarker key={key} center={pos} radius={11}
      pathOptions={{ color: "#111", weight: 3, fill: km === 0, fillColor: "#facc15", fillOpacity: 1 }}>
      {withLabel && label}
    </CircleMarker>
  );

  if (km === 0) return ring(overlap.closest_a, "touch", true);
  return (
    <>
      <Polyline positions={[overlap.closest_a, overlap.closest_b]}
        pathOptions={{ color: "#111", weight: 3, dashArray: "8 8" }} />
      {ring(overlap.closest_a, "ra", true)}
      {ring(overlap.closest_b, "rb", false)}
    </>
  );
}

export default function Map({ projects, overlaps, codes, selected, activeIds = null, activePairs = [], sidebarOpen = true }) {
  const inOverlap = useMemo(() => new Set(overlaps.flatMap((o) => [o.id_a, o.id_b])), [overlaps]);
  const byId = useMemo(() => Object.fromEntries(projects.map((p) => [p.id, p])), [projects]);
  const located = useMemo(() => projects.filter((p) => points(p).length > 0), [projects]);

  const selectionKey = selected ? `${selected.id_a}|${selected.id_b}` : "";
  const selectedProjects = useMemo(
    () => (selected ? [byId[selected.id_a], byId[selected.id_b]].filter(Boolean) : []),
    [byId, selectionKey]
  );
  const others = useMemo(() => {
    const ids = new Set(selectedProjects.map((p) => p.id));
    return located.filter((p) => !ids.has(p.id));
  }, [located, selectedProjects]);

  return (
    <div className="map-wrap">
      <MapContainer center={[33.2, -81.5]} zoom={7} {...MAP_OPTIONS}>
        {/* OpenStreetMap tiles: free, no API key. keepBuffer loads extra tiles around the view
            so panning doesn't show gray gaps. */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
          keepBuffer={4}
          updateWhenZooming={false}
        />

        {others.map((p) => (
          <ProjectShape
            key={p.id}
            p={p}
            color={utilityColor(p.utility, codes)}
            faded={selected ? true : activeIds ? !activeIds.has(p.id) : false}
            overlapping={inOverlap.has(p.id)}
          />
        ))}

        {/* selected pair drawn last so it sits on top */}
        {selectedProjects.map((p, i) => (
          // labels go left and right of the pair so they don't cover each other or the distance
          <ProjectShape key={`sel-${p.id}`} p={p} color={utilityColor(p.utility, codes)} selected overlapping
            side={labelSide(selectedProjects, i)} />
        ))}
        {selected && <DistanceLine key={`dist-${selected.rank}`} overlap={selected} />}
        {!selected && activePairs.filter((o) => o.closest_a).map((o) => (
          <PulseHalo key={`pulse-${o.rank}`} center={o.closest_a} />
        ))}

        <ZoomToSelection selectedProjects={selectedProjects} selectionKey={selectionKey} sidebarOpen={sidebarOpen} />
        <ZoomControl position="bottomright" />
      </MapContainer>

      <div className="legend glass">
        <div className="legend-items">
          {codes.map((c) => (
            <span key={c} className="legend-item">
              <span className="swatch" style={{ background: utilityColor(c, codes) }} />
              <span className="mono">{c}</span>
            </span>
          ))}
        </div>
        <div className="legend-note">Line: project between two substations · Thick: overlaps another utility</div>
        <div className="legend-note">Rings: nearest points of the selected pair · Hover for dates</div>
      </div>
    </div>
  );
}
