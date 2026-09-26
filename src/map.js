import "./styles.css";
import "leaflet/dist/leaflet.css";
import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import { divIcon, point } from "leaflet";

const API_BASE = process.env.REACT_APP_API_BASE || "http://localhost:8000";

const CONF_COLOR = { high: "#2ecc71", low: "#f1c40f", missing: "#e74c3c" };

const endpointIcon = (conf) =>
  new divIcon({
    className: "endpoint-marker",
    html: `<span style="background:${CONF_COLOR[conf] || CONF_COLOR.missing}"></span>`,
    iconSize: [16, 16],
  });

const createClusterCustomIcon = (cluster) =>
  new divIcon({
    html: `<span class="cluster-icon">${cluster.getChildCount()}</span>`,
    className: "custom-marker-cluster",
    iconSize: point(33, 33, true),
  });

export default function Map() {
  const [projects, setProjects] = useState([]);
  const [overlapIds, setOverlapIds] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/projects`).then((r) => r.json()),
      fetch(`${API_BASE}/api/overlaps`).then((r) => r.json()),
    ])
      .then(([proj, overlaps]) => {
        setProjects(proj);
        setOverlapIds(
          new Set(overlaps.flatMap((o) => [o.id_a, o.id_b]))
        );
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="map-status">Loading projects…</div>;
  if (error) return <div className="map-status">Failed to load: {error}</div>;

  // one dot per geocoded endpoint (a and b), colored by match confidence
  const points = projects.flatMap((p, i) => {
    const out = [];
    if (p.lat_a != null && p.lon_a != null) {
      out.push({
        key: `${p.id ?? i}-a`,
        pos: [p.lat_a, p.lon_a],
        conf: p.conf_a,
        label: `${p.name} — ${p.match_a || p.endpoint_a}`,
      });
    }
    if (p.lat_b != null && p.lon_b != null) {
      out.push({
        key: `${p.id ?? i}-b`,
        pos: [p.lat_b, p.lon_b],
        conf: p.conf_b,
        label: `${p.name} — ${p.match_b || p.endpoint_b}`,
      });
    }
    return out;
  });

  return (
    <MapContainer center={[33.5, -82]} zoom={7}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {/* one line per project, red + thicker if it overlaps another utility's project */}
      {projects.map((p, i) =>
        p.lat_a != null && p.lon_a != null && p.lat_b != null && p.lon_b != null ? (
          <Polyline
            key={`line-${p.id ?? i}`}
            positions={[
              [p.lat_a, p.lon_a],
              [p.lat_b, p.lon_b],
            ]}
            pathOptions={{
              color: overlapIds.has(p.id) ? "#e74c3c" : "#3498db",
              weight: overlapIds.has(p.id) ? 4 : 2,
            }}
          >
            <Popup>
              <strong>{p.name}</strong>
              <br />
              {p.utility}
              {overlapIds.has(p.id) && (
                <>
                  <br />
                  <em>Overlaps with another utility's project</em>
                </>
              )}
            </Popup>
          </Polyline>
        ) : null
      )}

      <MarkerClusterGroup chunkedLoading iconCreateFunction={createClusterCustomIcon}>
        {points.map((pt) => (
          <Marker key={pt.key} position={pt.pos} icon={endpointIcon(pt.conf)}>
            <Popup>{pt.label}</Popup>
          </Marker>
        ))}
      </MarkerClusterGroup>
    </MapContainer>
  );
}
