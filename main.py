"""GridLock API.

Startup builds (or loads the cached) pipeline once; every endpoint serves from memory.

Every route is under /api. Each project has a stable "id" ("DESC:6807 B"), and each
overlap carries id_a / id_b, so the frontend can link overlaps to projects on the map.

GET  /api/health                         pipeline + database status
GET  /api/projects                       all projects (filter: utility, located)
GET  /api/projects/{utility}/{project_id}
GET  /api/overlaps                       ranked overlaps (filter: tier, time_overlap, limit)
GET  /api/overlaps/{rank}                one overlap with both projects in full
GET  /api/validation                     data-quality report
POST /api/refresh                        re-run the pipeline (re-parse, re-split, re-locate, re-save)
POST /api/parse                          parse any PDF under data/ (Gemini fallback for new layouts)
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import pipeline
from read_pdf import read_pdf

BASE = Path(__file__).parent
STATE = {}

TIER_INFO = {
    "touching": "Projects touch or cross: must coordinate outage timing and crossing structures.",
    "right-of-way": "Under 1.6 km: can share land, access roads and permits.",
    "site logistics": "Under 8 km: can share laydown yards and deliveries.",
    "crews": "Under 40 km: can share crews, cranes and contractors.",
}


@asynccontextmanager
async def lifespan(app):
    STATE.update(pipeline.build())
    yield


app = FastAPI(title="GridLock", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)
router = APIRouter(prefix="/api")


# ---------- helpers ----------

PROJECT_KEYS = [
    "utility", "project_id", "name", "status", "in_service", "start_date", "total_cost", "page",
    "endpoint_a", "lat_a", "lon_a", "match_a", "conf_a",
    "endpoint_b", "lat_b", "lon_b", "match_b", "conf_b",
]


def _pid(utility, project_id):
    return f"{utility}:{project_id}"


def _project_out(r):
    out = {"id": _pid(r["utility"], r.get("project_id"))}
    out.update({k: r.get(k) for k in PROJECT_KEYS})
    out["utility_name"] = pipeline.UTILITIES.get(r["utility"], {}).get("name", r["utility"])
    out["located"] = r.get("lat_a") is not None or r.get("lat_b") is not None
    return out


def _find_project(utility, project_id):
    for r in STATE["records"]:
        if r["utility"] == utility and str(r.get("project_id")) == project_id:
            return r
    return None


def _overlap_out(o, full=False):
    out = o._asdict()
    out["id_a"], out["id_b"] = _pid(o.utility_a, o.project_a), _pid(o.utility_b, o.project_b)
    out["tier_info"] = TIER_INFO.get(o.tier)
    a, b = _find_project(o.utility_a, o.project_a), _find_project(o.utility_b, o.project_b)
    if full:
        out["project_a_detail"], out["project_b_detail"] = _project_out(a), _project_out(b)
    else:  # just enough geometry for the map
        out["geometry_a"] = {k: a.get(k) for k in ("lat_a", "lon_a", "lat_b", "lon_b")}
        out["geometry_b"] = {k: b.get(k) for k in ("lat_a", "lon_a", "lat_b", "lon_b")}
    return out


# ---------- routes ----------

@router.get("/health")
def health():
    return {
        "projects": len(STATE.get("records", [])),
        "overlaps": len(STATE.get("overlaps", [])),
        "endpoint_split": STATE.get("split_method"),
        "database": STATE.get("db"),
    }


@router.get("/projects")
def projects(utility: str | None = None, located: bool | None = None):
    out = [_project_out(r) for r in STATE["records"]]
    if utility:
        out = [p for p in out if p["utility"] == utility.upper()]
    if located is not None:
        out = [p for p in out if p["located"] == located]
    return out


@router.get("/projects/{utility}/{project_id}")
def project(utility: str, project_id: str):
    r = _find_project(utility.upper(), project_id)
    if not r:
        raise HTTPException(404, "project not found")
    related = [_overlap_out(o) for o in STATE["overlaps"]
               if (o.utility_a, o.project_a) == (r["utility"], project_id)
               or (o.utility_b, o.project_b) == (r["utility"], project_id)]
    return {**_project_out(r), "overlaps": related}


@router.get("/overlaps")
def overlaps(tier: str | None = None, time_overlap: bool | None = None, limit: int | None = None):
    out = STATE["overlaps"]
    if tier:
        out = [o for o in out if o.tier == tier]
    if time_overlap is not None:
        out = [o for o in out if o.time_overlap == time_overlap]
    return [_overlap_out(o) for o in out[:limit]]


@router.get("/overlaps/{rank}")
def overlap(rank: int):
    for o in STATE["overlaps"]:
        if o.rank == rank:
            return _overlap_out(o, full=True)
    raise HTTPException(404, "overlap not found")


@router.get("/validation")
def validation():
    checks = {}
    for v in STATE["validations"]:
        c = checks.setdefault(v["check"], {"passed": 0, "failed": 0})
        c["passed" if v["passed"] else "failed"] += 1
    issues = [v for v in STATE["validations"] if not v["passed"]]
    return {
        "projects": len(STATE["records"]),
        "located": sum(1 for r in STATE["records"]
                       if r.get("lat_a") is not None or r.get("lat_b") is not None),
        "endpoint_confidence": pipeline.location_summary(STATE["records"]),
        "checks": checks,
        "issues": issues,
    }


@router.post("/refresh")
def refresh():
    STATE.update(pipeline.build(force=True))
    return health()


class ParseRequest(BaseModel):
    path: str  # e.g. "/data/using-data/notgeorgia.pdf"


@router.post("/parse")
def parse(req: ParseRequest):
    """Parse a PDF under data/. Known layouts use regex; unknown ones fall back to Gemini."""
    target = (BASE / req.path.lstrip("/")).resolve()
    if not target.is_relative_to((BASE / "data").resolve()) or not target.is_file():
        raise HTTPException(400, "path must point to a PDF inside data/")
    records = read_pdf("/" + str(target.relative_to(BASE)))
    method = "regex"
    if not records:
        from gemini_agent import GeminiAgent
        records, method = GeminiAgent().extract_projects(target), "gemini"
    return {"method": method, "count": len(records), "projects": records}


app.include_router(router)
