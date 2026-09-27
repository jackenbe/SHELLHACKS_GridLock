"""Overlap engine.

Compares every project from one utility with every project from the other and
returns the pairs that are within 40 km, as ranked Overlap tuples.

Distance is measured between the closest points of the two projects, not their
centers (per the challenge spec). A project is treated as a straight line between
its two endpoint substations, or as a single point if only one is located.

Input records are dicts with:
    project_id, name, utility (or source), in_service (or in_service_date),
    optional start_date, lat_a, lon_a, lat_b, lon_b
"""
import math
from datetime import date, datetime
from typing import NamedTuple

EARTH_KM = 6371.0088
KM_PER_MI = 1.609344
MAX_KM = 40.0          # challenge cutoff (25 mi)
TOUCH_KM = 0.1         # closer than this = same substation / crossing
TIMELINE_DAYS = 365    # in-service dates this close = timeline overlap

# (upper bound in km, tier name). Order matters: first match wins.
TIERS = [
    (TOUCH_KM, "touching"),        # must coordinate outages / crossing structures
    (1.6, "right-of-way"),         # can share land, access roads, permits
    (8.0, "site logistics"),       # can share laydown yards, deliveries
    (MAX_KM, "crews"),             # can share crews and equipment
]


class Overlap(NamedTuple):
    rank: int
    project_a: str
    utility_a: str
    name_a: str
    project_b: str
    utility_b: str
    name_b: str
    distance_km: float
    distance_mi: float
    tier: str
    time_gap_days: int | None
    time_overlap: bool


# ---------- geometry ----------

def _points(rec):
    pts = []
    for end in ("a", "b"):
        lat, lon = rec.get(f"lat_{end}"), rec.get(f"lon_{end}")
        if lat is not None and lon is not None:
            pts.append((float(lat), float(lon)))
    return pts


def _to_km(pts, lat0, lon0):
    """Flat projection around (lat0, lon0). Accurate to well under 1% at 40 km scale."""
    ky = math.radians(1) * EARTH_KM
    kx = ky * math.cos(math.radians(lat0))
    return [((lon - lon0) * kx, (lat - lat0) * ky) for lat, lon in pts]


def _from_km(pt, lat0, lon0):
    """Inverse of _to_km: plane (x, y) in km back to (lat, lon)."""
    ky = math.radians(1) * EARTH_KM
    kx = ky * math.cos(math.radians(lat0))
    return (lat0 + pt[1] / ky, lon0 + pt[0] / kx)


def _nearest_on_segment(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return (ax + t * dx, ay + t * dy)


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(a, b, c, d):
    return (_orient(a, b, c) * _orient(a, b, d) < 0) and (_orient(c, d, a) * _orient(c, d, b) < 0)


def closest_points(rec_a, rec_b):
    """The nearest point on each project and the distance between them.

    Returns ((lat, lon) on A, (lat, lon) on B, km), or None if either has no coordinates.
    """
    pa, pb = _points(rec_a), _points(rec_b)
    if not pa or not pb:
        return None
    every = pa + pb
    lat0 = sum(p[0] for p in every) / len(every)
    lon0 = sum(p[1] for p in every) / len(every)
    A, B = _to_km(pa, lat0, lon0), _to_km(pb, lat0, lon0)
    a1, a2, b1, b2 = A[0], A[-1], B[0], B[-1]

    if _segments_cross(a1, a2, b1, b2):  # lines cross: the crossing point is on both
        rx, ry = a2[0] - a1[0], a2[1] - a1[1]
        sx, sy = b2[0] - b1[0], b2[1] - b1[1]
        t = ((b1[0] - a1[0]) * sy - (b1[1] - a1[1]) * sx) / (rx * sy - ry * sx)
        x = (a1[0] + t * rx, a1[1] + t * ry)
        return _from_km(x, lat0, lon0), _from_km(x, lat0, lon0), 0.0

    candidates = []
    for p in (a1, a2):                     # endpoint of A -> nearest point on B
        q = _nearest_on_segment(p, b1, b2)
        candidates.append((math.dist(p, q), p, q))
    for q in (b1, b2):                     # endpoint of B -> nearest point on A
        p = _nearest_on_segment(q, a1, a2)
        candidates.append((math.dist(p, q), p, q))
    km, p, q = min(candidates, key=lambda c: c[0])
    return _from_km(p, lat0, lon0), _from_km(q, lat0, lon0), km


def closest_km(rec_a, rec_b):
    """Closest distance in km between two projects, or None if either has no coordinates."""
    result = closest_points(rec_a, rec_b)
    return None if result is None else result[2]


# ---------- time ----------

def _date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            pass
    return None


def _timeline(rec_a, rec_b):
    """(gap in days between in-service dates, whether the build windows overlap)."""
    end_a = _date(rec_a.get("in_service") or rec_a.get("in_service_date"))
    end_b = _date(rec_b.get("in_service") or rec_b.get("in_service_date"))
    if not end_a or not end_b:
        return None, False
    gap = abs((end_a - end_b).days)
    start_a, start_b = _date(rec_a.get("start_date")), _date(rec_b.get("start_date"))
    if start_a and start_b:  # both build windows known: do they intersect?
        return gap, start_a <= end_b and start_b <= end_a
    return gap, gap <= TIMELINE_DAYS


# ---------- main entry ----------

def _utility(rec):
    return rec.get("utility") or rec.get("source")


def _tier(km):
    for limit, name in TIERS:
        if km < limit:
            return name
    return None


def find_overlaps(records, max_km=MAX_KM):
    """Return ranked Overlap tuples for every cross-utility pair within max_km.

    Ranking: distance tier first (touching > right-of-way > site logistics > crews),
    then timeline overlap, then distance, then time gap.
    """
    located = [r for r in records if _points(r)]
    hits = []
    for i, a in enumerate(located):
        for b in located[i + 1:]:
            if _utility(a) == _utility(b):
                continue
            km = closest_km(a, b)
            if km is None or km >= max_km:
                continue
            gap, same_window = _timeline(a, b)
            hits.append(Overlap(
                rank=0,
                project_a=a["project_id"], utility_a=_utility(a), name_a=a.get("name"),
                project_b=b["project_id"], utility_b=_utility(b), name_b=b.get("name"),
                distance_km=round(km, 2), distance_mi=round(km / KM_PER_MI, 2),
                tier=_tier(km), time_gap_days=gap, time_overlap=same_window,
            ))

    tier_order = {name: i for i, (_, name) in enumerate(TIERS)}
    hits.sort(key=lambda o: (
        tier_order[o.tier], not o.time_overlap, o.distance_km,
        o.time_gap_days if o.time_gap_days is not None else math.inf,
    ))
    return [o._replace(rank=i) for i, o in enumerate(hits, 1)]


def missing_coordinates(records):
    """Records the engine had to skip because no endpoint is located yet."""
    return [r for r in records if not _points(r)]
