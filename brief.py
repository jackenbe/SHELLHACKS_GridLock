"""Coordination memo for one overlap: what a planner would send to the other utility.

Gemini writes it from a fact sheet built only from GridLock's own data, then every number in
the draft is checked against that fact sheet. If Gemini is unavailable, or its draft contains
a number that is not in the data, a fact-only template memo is returned instead, so the memo
is never less accurate than the rest of the app.
"""
import hashlib
import json
import os
import re
from pathlib import Path

BASE = Path(__file__).parent
CACHE = BASE / "gemini_cache" / "briefs.json"

TIER_LABEL = {"touching": "Touching / crossing", "right-of-way": "Shared right-of-way (under 1.6 km)",
              "site logistics": "Shared site logistics (under 8 km)", "crews": "Shared crews (under 40 km)"}


def money(musd):
    if musd is None:
        return "unknown"
    if musd == 0:
        return "$0"
    return f"${musd:.1f}M" if musd >= 1 else f"${round(musd * 1000)}K"


def _project_lines(label, p, utility_name, near_name):
    start = p.get("start_date") or "not listed in the filing"
    lines = [
        f"{label}: {utility_name} ({p['utility']}), \"{p.get('name')}\", ID {p.get('project_id')}",
        f"  In service: {p.get('in_service') or 'not listed'}; construction start: {start}",
        f"  Source: {p['utility']} filing, PDF page {p.get('page') or 'unknown'}",
    ]
    if near_name:
        lines.append(f"  Closest point is at: {near_name}")
    return lines


def build_facts(o, a, b, impact, utility_names, near_a=None, near_b=None):
    """Plain-text fact sheet. The memo may only use what is written here."""
    lines = [
        f"Overlap rank #{o.rank}: {TIER_LABEL.get(o.tier, o.tier)}",
        f"Closest distance: {o.distance_km} km ({o.distance_mi} mi)",
    ]
    lines += _project_lines("Project A", a, utility_names.get(o.utility_a, o.utility_a), near_a)
    lines += _project_lines("Project B", b, utility_names.get(o.utility_b, o.utility_b), near_b)
    if o.time_gap_days is not None:
        lines.append(f"Timeline: in-service dates are {o.time_gap_days} days apart; build windows "
                     f"{'overlap' if o.time_overlap else 'do not overlap'}")
    if impact:
        lines.append(f"Project A cost: {money(impact['cost_a'])} ({impact['cost_a_basis']})")
        lines.append(f"Project B cost: {money(impact['cost_b'])} ({impact['cost_b_basis']})")
        for i in impact["items"]:
            when = "only if one schedule shifts" if i["needs_alignment"] else "with current schedules"
            lines.append(f"Saving: {i['label']}: {money(i['amount'])} ({i['detail']}; {when})")
        lines.append(f"Estimated savings: {money(impact['savings'])} with current schedules, "
                     f"up to {money(impact['savings_if_aligned'])} if schedules align")
        for r in impact["resources"]:
            lines.append(f"Resource not duplicated: {r}")
    lines.append("Estimates are planning-level (MISO cost guide, USDA land values, utility-reported costs).")
    return "\n".join(lines)


def template_memo(o, a, b, impact, utility_names):
    """Deterministic memo built only from the facts (used when Gemini can't be)."""
    ua, ub = utility_names.get(o.utility_a, o.utility_a), utility_names.get(o.utility_b, o.utility_b)
    when = ("Both are scheduled to be under construction at the same time."
            if o.time_overlap else
            f"Their in-service dates are {o.time_gap_days} days apart." if o.time_gap_days is not None
            else "One of the schedules is not listed.")
    parts = [
        f"Subject: Coordination opportunity: {a.get('name')} / {b.get('name')}",
        "",
        f"To: {ub} transmission planning",
        f"From: {ua} transmission planning",
        "",
        f"Our planned project \"{a.get('name')}\" (ID {a.get('project_id')}, in service "
        f"{a.get('in_service') or 'not listed'}) comes within {o.distance_km} km ({o.distance_mi} mi) of your "
        f"project \"{b.get('name')}\" (ID {b.get('project_id')}, in service {b.get('in_service') or 'not listed'}). "
        f"{when}",
        "",
        f"Overlap type: {TIER_LABEL.get(o.tier, o.tier)}.",
    ]
    if impact and impact["items"]:
        parts += ["", "What we could share:"]
        for i in impact["items"]:
            tag = " (if one schedule shifts)" if i["needs_alignment"] else ""
            parts.append(f"- {i['label']}: about {money(i['amount'])}{tag}")
        parts.append(f"Estimated savings: {money(impact['savings'])} with current schedules, up to "
                     f"{money(impact['savings_if_aligned'])} if schedules align (planning-level estimate).")
    parts += ["", "Suggested next step: a 30-minute call between our planning teams to compare "
              "construction schedules, staging areas and outage windows.", "",
              f"Sources: {o.utility_a} filing p. {a.get('page') or '?'}, {o.utility_b} filing p. {b.get('page') or '?'}."]
    return "\n".join(parts)


PROMPT = """You are a transmission planner at {from_utility}. Write a short coordination memo
(at most 220 words) to the transmission planning team at {to_utility} about the overlap below.

Rules:
- Use ONLY the facts below. Do not add any number, date, cost, distance or ID that is not in them.
- Copy every figure exactly as written in the facts (for example "$125K", "5.46 km", "2027-06-01").
- Include: a Subject line, the two projects, how close they are and when they are built,
  what could be shared and the estimated savings (say it is a planning-level estimate),
  and one concrete next step. Cite the filing pages.
- Plain text, no markdown headings.

FACTS
{facts}"""

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    return {n.replace(",", "") for n in NUMBER.findall(text)}


def unverified_numbers(memo, facts):
    """Numbers in the memo that do not appear anywhere in the fact sheet."""
    allowed = _numbers(facts) | {"30"}  # "30-minute call" is the only number we allow it to add
    return sorted(n for n in _numbers(memo) if n not in allowed and not (len(n) == 1))


def _cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def coordination_brief(o, a, b, impact, utility_names, near_a=None, near_b=None):
    facts = build_facts(o, a, b, impact, utility_names, near_a, near_b)
    key = hashlib.sha1(facts.encode()).hexdigest()[:16]
    cache = _cache()
    if key in cache:
        return cache[key]

    result = None
    note = None
    if os.getenv("GEMINI_API_KEY"):
        try:
            from google import genai
            from google.genai import types
            from gemini_agent import generate
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            resp = generate(client, PROMPT.format(
                from_utility=utility_names.get(o.utility_a, o.utility_a),
                to_utility=utility_names.get(o.utility_b, o.utility_b), facts=facts),
                types.GenerateContentConfig(temperature=0.2))
            draft = (resp.text or "").strip()
            bad = unverified_numbers(draft, facts)
            if draft and not bad:
                result = {"memo": draft, "source": "gemini", "checked": True}
            else:
                note = ("Gemini's draft used numbers that aren't in the data "
                        f"({', '.join(bad[:5])}), so a fact-only version is shown.") if draft else None
        except Exception as err:
            note = f"Gemini unavailable ({str(err)[:120]}), so a fact-only version is shown."
    if result is None:
        result = {"memo": template_memo(o, a, b, impact, utility_names), "source": "template",
                  "checked": True, "note": note}
    result["facts"] = facts

    if result["source"] == "gemini":  # templates are free to rebuild; only cache AI drafts
        cache[key] = result
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=1))
    return result
