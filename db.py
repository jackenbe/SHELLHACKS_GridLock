"""Database tables and save helpers (SQLAlchemy 2.x).

Tables
  projects     one row per planned project, with its located endpoints
  substations  OpenStreetMap substations used for matching
  overlaps     ranked cross-utility pairs from overlap.find_overlaps()
  validations  one row per (project, check), for the data-quality report

Uses DATABASE_URL from .env (Tiger Data), or the local Docker db when running in compose.
Call init_db() once at startup; the save_* helpers are safe to re-run (upserts / replaces).
"""
import os
from datetime import date, datetime

from dotenv import load_dotenv
from sqlalchemy import (BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint, create_engine, delete, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://gridlock:gridlock@localhost:5432/gridlock"
)
# pool_pre_ping: cloud Postgres drops idle connections, this reconnects instead of erroring
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---------- tables ----------

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("utility", "project_id", name="uq_project_per_utility"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    utility: Mapped[str] = mapped_column(String(80), index=True)       # "DESC" / "GPC" / full name
    project_id: Mapped[str] = mapped_column(String(60))                # utility's own ID
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(60))
    in_service: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)
    total_cost: Mapped[int | None] = mapped_column(BigInteger)         # dollars
    voltage_kv: Mapped[int | None] = mapped_column(Integer)
    source_page: Mapped[int | None] = mapped_column(Integer)

    endpoint_a: Mapped[str | None] = mapped_column(String(200))
    lat_a: Mapped[float | None] = mapped_column(Float)
    lon_a: Mapped[float | None] = mapped_column(Float)
    match_a: Mapped[str | None] = mapped_column(String(200))
    conf_a: Mapped[str | None] = mapped_column(String(20))             # high/low/unconfirmed/missing
    loc_source_a: Mapped[str | None] = mapped_column(String(20))       # known/osm/nominatim

    endpoint_b: Mapped[str | None] = mapped_column(String(200))
    lat_b: Mapped[float | None] = mapped_column(Float)
    lon_b: Mapped[float | None] = mapped_column(Float)
    match_b: Mapped[str | None] = mapped_column(String(200))
    conf_b: Mapped[str | None] = mapped_column(String(20))
    loc_source_b: Mapped[str | None] = mapped_column(String(20))

    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(),
                                                 onupdate=func.now())
    validations: Mapped[list["Validation"]] = relationship(back_populates="project",
                                                           cascade="all, delete-orphan")


class Substation(Base):
    __tablename__ = "substations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)      # OSM id, e.g. "way/123"
    name: Mapped[str] = mapped_column(String(200), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    operator: Mapped[str | None] = mapped_column(String(200))
    voltage: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(2), index=True)


class Overlap(Base):
    __tablename__ = "overlaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, index=True)
    project_a_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    project_b_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    distance_km: Mapped[float] = mapped_column(Float)
    distance_mi: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(30))       # touching/right-of-way/site logistics/crews
    time_gap_days: Mapped[int | None] = mapped_column(Integer)
    time_overlap: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)   # Gemini "what could be shared" (Phase 5)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project_a: Mapped[Project] = relationship(foreign_keys=[project_a_id])
    project_b: Mapped[Project] = relationship(foreign_keys=[project_b_id])


class Validation(Base):
    __tablename__ = "validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_pk: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"),
                                            index=True)
    check: Mapped[str] = mapped_column(String(60))      # e.g. "name", "date_parses", "coords_a"
    passed: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="validations")


# ---------- setup ----------

def init_db(drop=False):
    """Create all tables (drop=True wipes them first)."""
    if drop:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: `def route(db: Session = Depends(get_session))`."""
    with SessionLocal() as session:
        yield session


# ---------- save helpers ----------

def _insert(table):
    """Dialect-aware INSERT so upserts work on Postgres (and SQLite in tests)."""
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


def _date(value):
    if value is None or isinstance(value, date):
        return value.date() if isinstance(value, datetime) else value
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            pass
    return None


def _utility(rec):
    return rec.get("utility") or rec.get("source")


PROJECT_FIELDS = [
    "name", "status", "total_cost", "voltage_kv",
    "endpoint_a", "lat_a", "lon_a", "match_a", "conf_a", "loc_source_a",
    "endpoint_b", "lat_b", "lon_b", "match_b", "conf_b", "loc_source_b",
]


def save_projects(records):
    """Upsert pipeline records. Returns {(utility, project_id): projects.id}."""
    rows = []
    for r in records:
        if not r.get("project_id"):
            continue
        row = {"utility": _utility(r), "project_id": str(r["project_id"])}
        row.update({f: r.get(f) for f in PROJECT_FIELDS})
        row["in_service"] = _date(r.get("in_service") or r.get("in_service_date"))
        row["start_date"] = _date(r.get("start_date"))
        row["source_page"] = r.get("page") or r.get("source_page")
        rows.append(row)
    if not rows:
        return {}

    table = Project.__table__
    stmt = _insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["utility", "project_id"],
        set_={c: stmt.excluded[c] for c in rows[0] if c not in ("utility", "project_id")},
    )
    with SessionLocal.begin() as s:
        s.execute(stmt)
        ids = s.query(Project.id, Project.utility, Project.project_id).all()
    return {(u, p): i for i, u, p in ids}


def save_substations(substations):
    """Upsert OSM substations (from locate.fetch_substations())."""
    if not substations:
        return
    cols = ["id", "name", "lat", "lon", "operator", "voltage", "state"]
    rows = [{c: s.get(c) for c in cols} for s in substations]
    table = Substation.__table__
    with SessionLocal.begin() as sess:
        for i in range(0, len(rows), 1000):          # chunks keep each statement small
            stmt = _insert(table).values(rows[i:i + 1000])
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"], set_={c: stmt.excluded[c] for c in cols if c != "id"})
            sess.execute(stmt)


def save_overlaps(overlaps, id_map):
    """Replace the overlaps table with a fresh find_overlaps() result.

    overlaps: list of overlap.Overlap tuples. id_map: result of save_projects().
    """
    rows = []
    for o in overlaps:
        a = id_map.get((o.utility_a, o.project_a))
        b = id_map.get((o.utility_b, o.project_b))
        if a is None or b is None:
            continue
        rows.append({
            "rank": o.rank, "project_a_id": a, "project_b_id": b,
            "distance_km": o.distance_km, "distance_mi": o.distance_mi, "tier": o.tier,
            "time_gap_days": o.time_gap_days, "time_overlap": o.time_overlap,
        })
    with SessionLocal.begin() as s:
        s.execute(delete(Overlap))
        if rows:
            s.execute(Overlap.__table__.insert(), rows)
    return len(rows)


def save_validations(results, id_map):
    """Replace validation rows.

    results: [{"utility", "project_id", "check", "passed", "detail"}, ...]
    """
    rows = []
    for r in results:
        pk = id_map.get((r["utility"], str(r["project_id"])))
        if pk is not None:
            rows.append({"project_pk": pk, "check": r["check"], "passed": bool(r["passed"]),
                         "detail": r.get("detail")})
    with SessionLocal.begin() as s:
        s.execute(delete(Validation))
        if rows:
            s.execute(Validation.__table__.insert(), rows)
    return len(rows)


if __name__ == "__main__":
    init_db()
    print("Tables ready:", ", ".join(Base.metadata.tables))
