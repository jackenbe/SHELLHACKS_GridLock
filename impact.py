"""Money and resources saved if two overlapping projects are coordinated
(equivalently: wasted if they are planned separately).

Planning-level estimate. Every number comes from ASSUMPTIONS below, each with its source,
and the API exposes them so anyone can check the math.

Per overlap:
  1. Estimate each project's cost: the utility's own figure when the PDF has one (DESC),
     otherwise voltage x work type x straight-line length from MISO's cost guide.
  2. Count only savings that clearly follow from the overlap tier:
       - one mobilization instead of two      (build windows overlap today, or
                                               "if aligned": one project shifts its schedule)
       - one engineering/environmental study   (touching or right-of-way tier)
       - right-of-way land bought once         (touching or right-of-way tier, two lines)
  3. Totals count each project's mobilization/study savings once, even if the project
     appears in several overlaps.
"""
import math
import re

from overlap import _date, _nearest_on_segment, _to_km

# ---------- assumptions (all dollars in millions unless noted) ----------

SOURCES = {
    "miso": "MISO Transmission Cost Estimation Guide for MTEP24 (May 2024)",
    "usda": "USDA NASS Land Values 2026 Summary (July 2026)",
    "mob": "Levelset: mobilization/demobilization is typically 2-10% of contract cost",
}

# new single-circuit line, $M per mile (MISO Table 4.1-1, Louisiana column as the
# closest Southeastern proxy; includes contingency and AFUDC)
NEW_LINE_PER_MI = {69: 2.0, 115: 2.2, 138: 2.3, 161: 2.4, 230: 2.6, 345: 4.1}
# rebuild, $M per mile (MISO Table 4.1-3 gives $1.5M-$1.9M; scaled by voltage within that range)
REBUILD_PER_MI = {69: 1.5, 115: 1.5, 138: 1.6, 161: 1.6, 230: 1.7, 345: 1.9}
# reconductor, $M per mile (MISO: $0.33M at 69 kV; higher voltages interpolated)
RECONDUCTOR_PER_MI = {69: 0.33, 115: 0.45, 138: 0.5, 161: 0.55, 230: 0.65, 345: 0.8}
# substation work = one new position, $M (MISO Table 4.2-1; 161 and 230 kV interpolated)
SUBSTATION = {69: 1.3, 115: 1.5, 138: 1.7, 161: 1.9, 230: 2.5, 345: 3.4}
# right-of-way width in feet (MISO Table 3.1-1)
ROW_FT = {69: 80, 115: 90, 138: 95, 161: 100, 230: 125, 345: 175}
# average farm real estate value, $ per acre, 2026 (USDA NASS)
LAND_PER_ACRE = {"GA": 4950, "SC": 3000}
DEFAULT_LAND_PER_ACRE = 3000

MOBILIZATION_RATE = 0.05   # of the smaller project's cost (low-middle of the 2-10% range)
ENGINEERING_RATE = 0.03    # MISO: engineering, environmental studies, testing = 3% of cost
SHARED_CORRIDOR_KM = 1.6   # right-of-way tier distance from the challenge spec

STATE_OF = {"DESC": "SC", "GPC": "GA"}

ASSUMPTIONS = [
    {"item": "New line cost", "value": "$2.0M-$4.1M per mile by voltage (69-345 kV)", "source": SOURCES["miso"]},
    {"item": "Rebuild cost", "value": "$1.5M-$1.9M per mile", "source": SOURCES["miso"]},
    {"item": "Reconductor cost", "value": "$0.33M-$0.8M per mile (above 69 kV interpolated)", "source": SOURCES["miso"]},
    {"item": "Substation work", "value": "$1.3M-$3.4M per new position", "source": SOURCES["miso"]},
    {"item": "Line length", "value": "straight line between the two substations (real routes are longer, so costs are understated)", "source": "GridTalk"},
    {"item": "Right-of-way width", "value": "80-175 ft by voltage", "source": SOURCES["miso"]},
    {"item": "Land value", "value": "GA $4,950/acre, SC $3,000/acre", "source": SOURCES["usda"]},
    {"item": "Mobilization", "value": f"{MOBILIZATION_RATE:.0%} of the smaller project, only when build windows overlap", "source": SOURCES["mob"]},
    {"item": "Engineering / environmental study", "value": f"{ENGINEERING_RATE:.0%} of the smaller project, touching or right-of-way tier only", "source": SOURCES["miso"]},
    {"item": "Reported costs", "value": "used as-is when the utility's PDF lists them (DESC)", "source": "utility filing"},
]


# ---------- project cost ----------

KV_RE = re.compile(r"(\d{2,3})(?:\.\d+)?(?=[\s\-/\d.]*kV)", re.I)
SUBSTATION_WORDS = re.compile(
    r"CAPACITOR|BREAKER|\bBUS\b|REACTOR|STATCOM|TRANSFORMER|\bBANK\b|RELAY|SWITCH|VALVE|SUBSTATION|\bSUB\b",
    re.I)


def _kv_class(name):
    kvs = [int(k) for k in KV_RE.findall(name or "") if 34 <= int(k) <= 765]
    kv = max(kvs) if kvs else 115
    for c in (69, 115, 138, 161, 230):
        if kv <= c:
            return c
    return 345


def _miles(rec):
    if None in (rec.get("lat_a"), rec.get("lon_a"), rec.get("lat_b"), rec.get("lon_b")):
        return None
    la1, lo1, la2, lo2 = map(math.radians, (rec["lat_a"], rec["lon_a"], rec["lat_b"], rec["lon_b"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def project_cost(rec):
    """(cost in $M, how it was estimated)."""
    if rec.get("total_cost"):
        return rec["total_cost"] / 1e6, "reported by the utility"
    name = rec.get("name") or ""
    kv = _kv_class(name)
    miles = _miles(rec)
    if miles is None or (SUBSTATION_WORDS.search(name) and "LINE" not in name.upper()):
        return SUBSTATION[kv], f"substation work at {kv} kV (MISO)"
    upper = name.upper()
    if "RECONDUCTOR" in upper:
        rate, kind = RECONDUCTOR_PER_MI[kv], "reconductor"
    elif "REBUILD" in upper or "REPLACE" in upper:
        rate, kind = REBUILD_PER_MI[kv], "rebuild"
    else:
        rate, kind = NEW_LINE_PER_MI[kv], "new line"
    return rate * miles, f"{kind}, {miles:.1f} mi at {kv} kV (MISO ${rate}M/mi)"


# ---------- shared corridor ----------

def _shared_corridor_miles(a, b):
    """Miles of the shorter line that run within 1.6 km of the other line."""
    if _miles(a) is None or _miles(b) is None:
        return 0.0
    short, long_ = (a, b) if _miles(a) <= _miles(b) else (b, a)
    pts = [(short["lat_a"], short["lon_a"]), (short["lat_b"], short["lon_b"]),
           (long_["lat_a"], long_["lon_a"]), (long_["lat_b"], long_["lon_b"])]
    lat0 = sum(p[0] for p in pts) / 4
    lon0 = sum(p[1] for p in pts) / 4
    s1, s2, l1, l2 = _to_km(pts, lat0, lon0)
    n = 50
    close = 0
    for i in range(n + 1):
        t = i / n
        p = (s1[0] + t * (s2[0] - s1[0]), s1[1] + t * (s2[1] - s1[1]))
        if math.dist(p, _nearest_on_segment(p, l1, l2)) <= SHARED_CORRIDOR_KM:
            close += 1
    return _miles(short) * close / (n + 1)


# ---------- per overlap ----------

def _state(rec):
    return STATE_OF.get(rec.get("utility"))


def estimate(a, b, overlap):
    cost_a, basis_a = project_cost(a)
    cost_b, basis_b = project_cost(b)
    smaller = min(cost_a, cost_b)
    items, resources = [], []

    # crews can only be shared if both jobs run at the same time: counted today when the
    # build windows already overlap, otherwise only in the "if schedules are aligned" scenario
    items.append({"key": "mobilization", "label": "One crew mobilization instead of two",
                  "amount": MOBILIZATION_RATE * smaller,
                  "needs_alignment": not overlap.time_overlap,
                  "detail": f"{MOBILIZATION_RATE:.0%} of the smaller project (${smaller:.1f}M)"
                            + ("" if overlap.time_overlap else "; needs one schedule to shift")})
    resources.append("1 crew and equipment mobilization avoided"
                     + ("" if overlap.time_overlap else " (if schedules align)"))
    if overlap.tier != "crews":
        resources.append("1 shared laydown / staging yard"
                         + ("" if overlap.time_overlap else " (if schedules align)"))

    if overlap.tier in ("touching", "right-of-way"):
        items.append({"key": "engineering", "label": "One engineering / environmental study",
                      "amount": ENGINEERING_RATE * smaller, "needs_alignment": False,
                      "detail": f"{ENGINEERING_RATE:.0%} of the smaller project, one study of the shared area"})
        resources.append("1 environmental review of the same area avoided")

        shared_mi = _shared_corridor_miles(a, b)
        if shared_mi > 0.05:
            width = ROW_FT[min(_kv_class(a.get("name")), _kv_class(b.get("name")))]
            acres = shared_mi * 5280 * width / 43560
            per_acre = min(LAND_PER_ACRE.get(_state(a), DEFAULT_LAND_PER_ACRE),
                           LAND_PER_ACRE.get(_state(b), DEFAULT_LAND_PER_ACRE))
            items.append({"key": "row", "label": "Right-of-way land bought once",
                          "amount": acres * per_acre / 1e6, "needs_alignment": False,
                          "detail": f"{shared_mi:.1f} mi of corridor x {width} ft = {acres:.0f} acres at ${per_acre:,}/acre"})
            resources.append(f"{acres:.0f} acres of right-of-way not acquired twice")

    if overlap.tier == "touching":
        resources.append("1 combined outage window instead of 2")

    return {
        "cost_a": round(cost_a, 2), "cost_a_basis": basis_a,
        "cost_b": round(cost_b, 2), "cost_b_basis": basis_b,
        "items": [{**i, "amount": round(i["amount"], 3)} for i in items],
        "savings": round(sum(i["amount"] for i in items if not i["needs_alignment"]), 3),
        "savings_if_aligned": round(sum(i["amount"] for i in items), 3),
        "resources": resources,
    }


def _total(per_pair, aligned, counted=None):
    """Sum savings without double counting: a project saves its mobilization / study once,
    so the best pairs are taken first and later pairs skip items for projects already used.
    If `counted` is a dict, it is filled with what each pair adds to the total."""
    used = {"mobilization": set(), "engineering": set()}
    total, pairs, acres = 0.0, 0, 0.0
    key_of = "savings_if_aligned" if aligned else "savings"
    for key, est in sorted(per_pair.items(), key=lambda kv: -kv[1][key_of]):
        pa, pb = key[:2], key[2:]
        pair_total = 0.0
        for item in est["items"]:
            if item["needs_alignment"] and not aligned:
                continue
            if item["key"] in used:
                if pa in used[item["key"]] or pb in used[item["key"]]:
                    continue
                used[item["key"]].update((pa, pb))
            pair_total += item["amount"]
            if item["key"] == "row":
                acres += float(item["detail"].split(" = ")[1].split(" acres")[0])
        pairs += pair_total > 0
        total += pair_total
        if counted is not None:
            counted[key] = pair_total
    return {
        "savings_musd": round(total, 2),
        "pairs": pairs,
        "mobilizations_avoided": len(used["mobilization"]) // 2,
        "studies_avoided": len(used["engineering"]) // 2,
        "row_acres_shared": round(acres),
    }


def _year(value):
    d = _date(value)
    return d.year if d else None


def _timeline(per_pair, by_id):
    """When the savings are lost if the utilities plan separately. A pair's savings are gone
    once both projects are built on their own, so they are booked in the in-service year of
    the later project. Amounts are the same no-double-counting shares as the totals, so the
    running sum ends at the totals."""
    today, aligned = {}, {}
    _total(per_pair, aligned=False, counted=today)
    _total(per_pair, aligned=True, counted=aligned)
    years, undated = {}, {"today": 0.0, "aligned": 0.0, "pairs": 0}
    for key in per_pair:
        t, a = today.get(key, 0.0), aligned.get(key, 0.0)
        if t <= 0 and a <= 0:
            continue
        ys = [_year(by_id.get((key[0], str(key[1])), {}).get("in_service")),
              _year(by_id.get((key[2], str(key[3])), {}).get("in_service"))]
        slot = undated if None in ys else years.setdefault(max(ys), {"today": 0.0, "aligned": 0.0, "pairs": 0})
        slot["today"] += t
        slot["aligned"] += a
        slot["pairs"] += 1
    return {
        "by_year": [{"year": y, "today_musd": round(v["today"], 3),
                     "aligned_musd": round(v["aligned"], 3), "pairs": v["pairs"]}
                    for y, v in sorted(years.items())],
        "undated": {"today_musd": round(undated["today"], 3),
                    "aligned_musd": round(undated["aligned"], 3), "pairs": undated["pairs"]},
        "rule": "Savings are lost in the in-service year of the later project in each pair, "
                "once both have been built separately.",
    }


def estimate_all(records, overlaps):
    """{(id_a, id_b): estimate} plus a no-double-counting total."""
    by_id = {(r["utility"], str(r.get("project_id"))): r for r in records}
    per_pair = {}
    for o in overlaps:
        a = by_id.get((o.utility_a, str(o.project_a)))
        b = by_id.get((o.utility_b, str(o.project_b)))
        if a and b:
            per_pair[(o.utility_a, o.project_a, o.utility_b, o.project_b)] = estimate(a, b, o)

    now = _total(per_pair, aligned=False)
    aligned = _total(per_pair, aligned=True)
    summary = {
        "current_schedules": now,        # windows that already overlap
        "if_schedules_aligned": aligned,  # plus pairs where one project shifts its schedule
        "note": "Planning-level estimate of what coordination could save (what separate planning "
                "wastes). Each project's savings are counted once in the total.",
        "assumptions": ASSUMPTIONS,
        "timeline": _timeline(per_pair, by_id),  # when the savings are lost, year by year
    }
    return per_pair, summary
