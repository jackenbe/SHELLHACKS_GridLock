"""Find the pages in any utility PDF that list planned construction projects.

Works on layout-agnostic signals instead of per-utility rules:
- dates (planned projects always have an in-service / need date)
- voltage mentions (115kV, 230 KV, ...)
- construction verbs and equipment words (rebuild, substation, reconductor, ...)
- field labels that project listings use (Project ID, Need Date, Estimated Cost, ...)
Pages whose heading says cancelled / completed / operating guide etc. are dropped.
The cutoff is relative to the document's own best pages, so it adapts per PDF.
"""
import re
import pypdfium2 as pdfium

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"                    # 12/31/2025, 6/1/26
    r"|\b\d{1,2}/\d{4}\b"                              # 06/2026
    rf"|\b{MONTHS}[\s/,.-]*\d{{4}}\b"                    # June/2026, Dec 2031
    r"|\b(?:start|end|in[- ]service|completion|need|commercial operation)\b[^\n\d]{0,25}"
    r"\b20[2-4]\d\b",                                   # "Start date: 2025"
    re.I,
)
KV = re.compile(r"\b\d{2,3}\s?kV\b", re.I)
TERMS = re.compile(
    r"\b(rebuild|reconductor|construct\w*|install\w*|upgrade\w*|substation|sub|"
    r"line|tap|bus|breaker|capacitor|transformer|autobank|switching|fold-in)\b",
    re.I,
)
LABELS = re.compile(
    r"project\s+(id|name|status|description|need)|in-service|need\s+date|"
    r"estimated\s+(project\s+)?cost|start\s+date|terminals?\b|point\s+of\s+origin|"
    r"line\s+length|construction\s+timing|proposed\s+(transmission|power)\s+lines?",
    re.I,
)
# checked only in the top of the page, where section headings live
EXCLUDE = re.compile(
    r"\b(cancel+ed|completed|removed from|operating guides?|table of contents|"
    r"glossary|acronyms|index|purchased power|fuel (requirements|use|price)|emissions|"
    r"load forecast|generating (facilit\w*|units?)|power plant specifications)\b",
    re.I,
)
HEAD_LINES = 12
MIN_SCORE = 12          # absolute floor
RELATIVE_CUTOFF = 0.5   # of the document's 90th-percentile page score
MAX_GAP = 2             # pages allowed between hits in the same section


def page_texts(path):
    """Fast text for every page (pypdfium2 is ~50x faster than pdfplumber)."""
    pdf = pdfium.PdfDocument(path)
    try:
        return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()


def score_page(text):
    lines = [l for l in text.splitlines() if l.strip()]
    head = "\n".join(lines[:HEAD_LINES])
    dates = len(DATE.findall(text))
    feats = {
        "dates": dates,
        "kv": len(KV.findall(text)),
        "terms": len(TERMS.findall(text)),
        "labels": len(LABELS.findall(text)),
        "excluded": bool(EXCLUDE.search(head)),
    }
    if dates == 0 or feats["excluded"]:
        feats["score"] = 0
    else:
        feats["score"] = (
            3 * min(feats["labels"], 6)
            + min(dates, 15)
            + min(feats["kv"], 15)
            + min(feats["terms"], 15)
        )
    return feats


def find_project_pages(path):
    """Return [(page_number, text, features)] for pages that look like project listings."""
    texts = page_texts(path)
    scored = [(i + 1, t, score_page(t)) for i, t in enumerate(texts)]

    positive = sorted(f["score"] for _, _, f in scored if f["score"] > 0)
    if not positive:
        return []
    p90 = positive[int(0.9 * (len(positive) - 1))]
    cutoff = max(MIN_SCORE, RELATIVE_CUTOFF * p90)
    hits = [(n, t, f) for n, t, f in scored if f["score"] >= cutoff]

    # Real listings come in runs of pages. Drop stray single pages
    # (appendix forms, schedules) unless they score like the best pages.
    nums = {n for n, _, _ in hits}
    return [
        (n, t, f) for n, t, f in hits
        if (n - 1 in nums or n + 1 in nums) or f["score"] >= p90 or len(texts) <= 3
    ]


def find_sections(path):
    """Group project pages into contiguous sections and guess each one's layout.

    layout "form":  one project per page (label: value blocks, e.g. DESC, GPC detail pages)
    layout "table": many projects per page (rows, e.g. GPC 10-year project list)
    """
    sections = []
    for n, t, f in find_project_pages(path):
        if sections and n - sections[-1]["pages"][-1] <= MAX_GAP + 1:
            sections[-1]["pages"].append(n)
            sections[-1]["dates"].append(f["dates"])
        else:
            sections.append({"pages": [n], "dates": [f["dates"]]})
    for s in sections:
        d = sorted(s.pop("dates"))
        s["layout"] = "table" if d[len(d) // 2] > 3 else "form"
        s["range"] = (s["pages"][0], s["pages"][-1])
    return sections


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        print(path)
        for s in find_sections(path):
            print(f"  pages {s['range'][0]}-{s['range'][1]} ({len(s['pages'])} pages, {s['layout']})")
