import "leaflet/dist/leaflet.css";
import { useEffect } from "react";
import {
  CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, useMap,
} from "react-leaflet";
import { utilityColor } from "./colors";
import { fmtMonth } from "./dates";

// Every located project is drawn in its utility's color:
//   both substations found -> a line between them (with a dot at each end); one found -> a dot.
// Thick = overlaps another utility's project. Hover anything for its name and in-service date.
// Selecting an overlap fades everything else, labels both projects, and draws a dashed line
// between their nearest points with the distance on it.

function points(p) {
  const pts = [];
  if (p.lat_a != null && p.lon_a != null) pts.push([p.lat_a, p.lon_a]);
  if (p.lat_b != null && p.lon_b != null) pts.push([p.lat_b, p.lon_b]);
  return pts;
}

function ZoomToSelection({ selectedProjects }) {
  const map = useMap();
  useEffect(() => {
    const pts = selectedProjects.flatMap(points);
    if (pts.length) map.flyToBounds(pts, { padding: [90, 90], maxZoom: 11 });
  }, [map, selectedProjects]);
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
    </Popup>
  );
}

function ProjectShape({ p, color, selected, faded, overlapping }) {
  const pts = points(p);
  const opacity = faded ? 0.25 : 0.95;
  const label = (
    <Tooltip sticky={!selected} permanent={selected} direction="top" className={selected ? "project-label" : ""}>
      <b>{p.utility}</b> {p.name}
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
    <Tooltip permanent direction="top" offset={[0, -12]} className="distance-label">
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

export default function Map({ projects, overlaps, codes, selected }) {
  const inOverlap = new Set(overlaps.flatMap((o) => [o.id_a, o.id_b]));
  const selectedIds = new Set(selected ? [selected.id_a, selected.id_b] : []);
  const byId = Object.fromEntries(projects.map((p) => [p.id, p]));
  const selectedProjects = selected ? [byId[selected.id_a], byId[selected.id_b]].filter(Boolean) : [];

  const located = projects.filter((p) => points(p).length > 0);
  const others = located.filter((p) => !selectedIds.has(p.id));

  return (
    <div className="map-wrap">
      <MapContainer center={[33.2, -81.5]} zoom={7}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {others.map((p) => (
          <ProjectShape
            key={p.id}
            p={p}
            color={utilityColor(p.utility, codes)}
            faded={!!selected}
            overlapping={inOverlap.has(p.id)}
          />
        ))}

        {/* selected pair drawn last so it sits on top */}
        {selectedProjects.map((p) => (
          <ProjectShape key={`sel-${p.id}`} p={p} color={utilityColor(p.utility, codes)} selected overlapping />
        ))}
        {selected && <DistanceLine key={`dist-${selected.rank}`} overlap={selected} />}

        <ZoomToSelection selectedProjects={selectedProjects} />
      </MapContainer>

      <div className="legend">
        {codes.map((c) => (
          <div key={c}>
            <span className="swatch" style={{ background: utilityColor(c, codes) }} /> {c}
          </div>
        ))}
        <div className="legend-note">line = project between two substations (dots)</div>
        <div className="legend-note">thick = overlaps another utility</div>
        <div className="legend-note">black rings = where a selected pair comes closest</div>
        <div className="legend-note">hover a project for its dates</div>
      </div>
    </div>
  );
}
