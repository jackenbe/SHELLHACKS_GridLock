import { sourceUrl } from "./api";

const CONF = { high: "high confidence", low: "low confidence", unconfirmed: "unconfirmed", missing: "not found" };
const SOURCE = { known: "Sperry-verified point", osm: "OpenStreetMap", nominatim: "place search" };

function End({ name, match, conf, src }) {
  if (!name) return null;
  return (
    <div className="ev-end">
      <span className={`conf-dot ${conf || "missing"}`} />
      <span className="ev-name">{name}</span>
      <span className="muted">
        {match && match !== name ? ` → ${match}` : ""} · {CONF[conf] || "not found"}
        {src ? ` · ${SOURCE[src] || src}` : ""}
      </span>
    </div>
  );
}

// Where every number came from: the filing page, and how each substation was located.
export default function Evidence({ projects }) {
  return (
    <div className="detail-card evidence">
      <div className="detail-title">Evidence</div>
      {projects.filter(Boolean).map((p) => (
        <div className="ev-project" key={p.id}>
          <div className="ev-head">
            <span className="mono">{p.utility}</span>
            <span className="muted mono">ID {p.project_id}</span>
            <a className="ev-link" href={sourceUrl(p)} target="_blank" rel="noreferrer">
              Filing{p.page ? ` p. ${p.page}` : ""} ↗
            </a>
          </div>
          <End name={p.endpoint_a} match={p.match_a} conf={p.conf_a} src={p.loc_source_a} />
          <End name={p.endpoint_b} match={p.match_b} conf={p.conf_b} src={p.loc_source_b} />
        </div>
      ))}
    </div>
  );
}
