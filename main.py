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
GET  /api/impact                         money + resources saved by coordinating (and assumptions)
POST /api/overlaps/{rank}/brief          coordination memo for one overlap (Gemini, fact-checked)
GET  /api/source/{utility}               the utility's original PDF (add #page=N to open a page)
GET  /api/utilities                      utilities loaded (preloaded + uploaded)
DELETE /api/utilities/{code}             remove an uploaded utility (preloaded ones stay)
POST /api/upload                         upload a utility's PDF (multipart) -> {job_id}
POST /api/find-plans                     search planning portals + Gemini for a utility's plan PDFs
POST /api/import-url                     download a plan PDF from a link and process it -> {job_id}
GET  /api/upload/{job_id}                upload progress: status, progress %, message, result
POST /api/refresh                        re-run the pipeline (re-parse, re-split, re-locate, re-save)
"""
import hashlib
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import brief
import finder
import pipeline
from overlap import closest_points

BASE = Path(__file__).parent
UPLOAD_DIR = BASE / "uploads"
MAX_UPLOAD_MB = 60
STATE = {}
JOBS = {}  # upload job_id -> {status, progress, message, result}

TIER_INFO = {
    "touching": "Projects touch or cross: must coordinate outage timing and crossing structures.",
    "right-of-way": "Under 1.6 km: can share land, access roads and permits.",
    "site logistics": "Under 8 km: can share laydown yards and deliveries.",
    "crews": "Under 40 km: can share crews, cranes and contractors.",
}


@asynccontextmanager
async def lifespan(app):
    with pipeline.LOCK:
        STATE.update(pipeline.build())
    yield


app = FastAPI(title="GridLock", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[  # React dev servers: create-react-app (3000) and Vite (5173)
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
router = APIRouter(prefix="/api")


# ---------- helpers ----------

PROJECT_KEYS = [
    "utility", "project_id", "name", "status", "in_service", "start_date", "total_cost", "page",
    "endpoint_a", "lat_a", "lon_a", "match_a", "conf_a", "loc_source_a",
    "endpoint_b", "lat_b", "lon_b", "match_b", "conf_b", "loc_source_b",
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
        if r["utility"] == utility and str(r.get("project_id")) == str(project_id):
            return r
    return None


def _near_name(rec, pt):
    """Substation name if the nearest point is one of the project's ends, else None (mid-line)."""
    for end in ("a", "b"):
        lat, lon = rec.get(f"lat_{end}"), rec.get(f"lon_{end}")
        if lat is not None and abs(lat - pt[0]) < 1e-5 and abs(lon - pt[1]) < 1e-5:
            name = rec.get(f"match_{end}") or rec.get(f"endpoint_{end}") or ""
            # 'THURMOND DAM (USA) #5 115KV REBUILD' -> 'THURMOND DAM'
            name = re.split(r"\b\d+(?:/\d+)?\s?kV\b", name, flags=re.I)[0]
            name = re.sub(r"\(.*?\)|#\s*\d+", " ", name)
            return " ".join(name.split()) or None
    return None


def _overlap_out(o, full=False):
    out = o._asdict()
    out["id_a"], out["id_b"] = _pid(o.utility_a, o.project_a), _pid(o.utility_b, o.project_b)
    out["tier_info"] = TIER_INFO.get(o.tier)
    a, b = _find_project(o.utility_a, o.project_a), _find_project(o.utility_b, o.project_b)
    near = closest_points(a, b) if a and b else None  # nearest points, for the map's distance line
    if near:
        out["closest_a"] = [round(near[0][0], 6), round(near[0][1], 6)]
        out["closest_b"] = [round(near[1][0], 6), round(near[1][1], 6)]
        out["closest_name_a"], out["closest_name_b"] = _near_name(a, near[0]), _near_name(b, near[1])
    per_pair = STATE.get("impact", ({}, {}))[0]
    out["impact"] = per_pair.get((o.utility_a, o.project_a, o.utility_b, o.project_b))
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


@router.post("/overlaps/{rank}/brief")
def overlap_brief(rank: int):
    """Coordination memo: Gemini drafts it from GridLock's data, every number is checked."""
    o = next((x for x in STATE["overlaps"] if x.rank == rank), None)
    if o is None:
        raise HTTPException(404, "overlap not found")
    a, b = _find_project(o.utility_a, o.project_a), _find_project(o.utility_b, o.project_b)
    near = closest_points(a, b) if a and b else None
    names = {code: u["name"] for code, u in pipeline.UTILITIES.items()}
    impact_ = STATE["impact"][0].get((o.utility_a, o.project_a, o.utility_b, o.project_b))
    return brief.coordination_brief(o, a, b, impact_, names,
                                    _near_name(a, near[0]) if near else None,
                                    _near_name(b, near[1]) if near else None)


@router.get("/source/{code}")
def source_pdf(code: str):
    """The utility's original filing, shown inline so links can jump to #page=N."""
    u = pipeline.UTILITIES.get(code.upper())
    if not u:
        raise HTTPException(404, "unknown utility")
    rel = Path(u["pdf"].lstrip("/"))
    path = BASE / rel
    if ".." in rel.parts or not path.is_file():
        raise HTTPException(404, "source file not found")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{code.upper()}-filing.pdf"'})


@router.get("/impact")
def impact():
    return STATE["impact"][1]


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
    with pipeline.LOCK:
        STATE.update(pipeline.build(force=True))
    return health()


# ---------- uploads ----------

@router.get("/utilities")
def utilities():
    counts = {}
    for r in STATE["records"]:
        counts[r["utility"]] = counts.get(r["utility"], 0) + 1
    return [{"code": code, "name": u["name"], "state": u["state"], "projects": counts.get(code, 0),
             "preloaded": code in pipeline.PRELOADED}
            for code, u in pipeline.UTILITIES.items()]


@router.delete("/utilities/{code}")
def remove_utility(code: str):
    try:
        with pipeline.LOCK:
            pipeline.remove_utility(STATE, code.upper())
    except KeyError:
        raise HTTPException(404, "unknown utility")
    except ValueError as err:
        raise HTTPException(400, str(err))
    return utilities()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utility_with_same_file(digest):
    """Code of an already-loaded utility whose PDF is byte-for-byte this upload, if any."""
    for code, u in pipeline.UTILITIES.items():
        path = BASE / u["pdf"].lstrip("/")
        if path.exists() and _sha256(path) == digest:
            return code
    return None


def _utility_code(name):
    """Reuse the code of a utility with the same name (so re-uploads replace it),
    otherwise build one from the initials: 'Duke Energy Carolinas' -> 'DEC'."""
    for code, u in pipeline.UTILITIES.items():
        if u["name"].strip().lower() == name.strip().lower() or code == name.strip().upper():
            return code
    words = re.findall(r"[A-Za-z0-9]+", name)
    if len(words) == 1:  # already an abbreviation, e.g. "FPL", "TVA"
        code = words[0].upper()[:6]
    else:                # initials: "Duke Energy Carolinas" -> "DEC"
        code = "".join(w[0] for w in words).upper()[:6] or "UTIL"
    base, n = code, 2
    while code in pipeline.UTILITIES:  # different name, same initials
        code, n = f"{base}{n}", n + 1
    return code


def _run_upload(job_id, code, name, us_state, pdf):
    job = JOBS[job_id]

    def progress(pct, msg):
        job.update(status="running", progress=pct, message=msg)

    try:
        with pipeline.LOCK:
            job.update(result=pipeline.add_utility(STATE, code, name, us_state, pdf, progress),
                       status="done", progress=100, message="Done")
    except Exception as err:
        job.update(status="error", message=str(err))


def _check_inputs(utility_name, state):
    us_state = state.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", us_state):
        raise HTTPException(400, "state must be a 2-letter code like SC or GA")
    if not utility_name.strip():
        raise HTTPException(400, "utility_name is required")
    return utility_name.strip(), us_state


def _store_pdf(data, utility_name, us_state):
    """Save the PDF and decide which utility it belongs to. Returns (code, name, state, pdf, note)."""
    if not data.startswith(b"%PDF"):
        raise ValueError("That file is not a PDF")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"PDF is larger than {MAX_UPLOAD_MB} MB")
    full_digest = hashlib.sha256(data).hexdigest()
    same = _utility_with_same_file(full_digest)
    if same:  # same file as a loaded utility: refresh that one instead of adding a duplicate
        u = pipeline.UTILITIES[same]
        note = f"This is the same file as {u['name']}, so it replaced {same} instead of adding a copy."
        return same, u["name"], u["state"], u["pdf"], note
    UPLOAD_DIR.mkdir(exist_ok=True)
    pdf = f"/uploads/{full_digest[:16]}.pdf"
    (BASE / pdf.lstrip("/")).write_bytes(data)
    return _utility_code(utility_name), utility_name, us_state, pdf, None


def _new_job(code):
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "utility": code, "status": "queued", "progress": 0,
                    "message": "Queued", "note": None, "result": None}
    return JOBS[job_id]


@router.post("/upload")
def upload(background: BackgroundTasks,
           file: UploadFile = File(...),
           utility_name: str = Form(...),
           state: str = Form(...)):
    """Upload one utility's planning PDF. Processing runs in the background; poll the job."""
    name, us_state = _check_inputs(utility_name, state)
    try:
        code, name, us_state, pdf, note = _store_pdf(file.file.read(), name, us_state)
    except ValueError as err:
        raise HTTPException(400, str(err))
    job = _new_job(code)
    job["note"] = note
    background.add_task(_run_upload, job["job_id"], code, name, us_state, pdf)
    return job


# ---------- find plans online ----------

class FindRequest(BaseModel):
    utility_name: str
    state: str


class ImportRequest(BaseModel):
    url: str
    utility_name: str
    state: str


@router.post("/find-plans")
def find_plans(req: FindRequest):
    """Search planning portals (and Gemini + Google Search) for this utility's plan PDFs."""
    name, us_state = _check_inputs(req.utility_name, req.state)
    return finder.find_plans(name, us_state)


def _run_import(job_id, url, name, us_state):
    job = JOBS[job_id]
    try:
        job.update(status="running", progress=2, message="Downloading the PDF")
        code, name, us_state, pdf, note = _store_pdf(finder.download_pdf(url), name, us_state)
        job.update(utility=code, note=note)
    except Exception as err:
        job.update(status="error", message=f"Could not import that link: {err}")
        return
    _run_upload(job_id, code, name, us_state, pdf)


@router.post("/import-url")
def import_url(req: ImportRequest, background: BackgroundTasks):
    """Download a plan PDF from a link (e.g. a /find-plans result) and process it like an upload."""
    name, us_state = _check_inputs(req.utility_name, req.state)
    try:
        finder.check_public_url(req.url)
    except (ValueError, OSError) as err:
        raise HTTPException(400, str(err))
    job = _new_job(_utility_code(name))
    background.add_task(_run_import, job["job_id"], req.url, name, us_state)
    return job


@router.get("/upload/{job_id}")
def upload_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    return JOBS[job_id]


app.include_router(router)
