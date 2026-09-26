import re
from pathlib import Path
from page_detect import find_project_pages

DATE = r"(\d{1,2}/\d{1,2}/\d{2,4})"

# One template per known page layout. Each maps a field to a regex whose
# group(1) is the value. read_pdf() tries every template on every detected
# page and keeps whichever one finds a project_id.
TEMPLATES = {
    "DESC": {
        "name":       r"5 Year Budget\s+(.+?)\s+Project ID",
        "project_id": r"Project ID\s+(.+)",
        "status":     r"Project Status\s+(.+)",
        "in_service": r"Planned In-Service Date\s+" + DATE,
        "total_cost": r"(\$[\d,]+)\s*$",   # last $ amount on the cost row = Total
    },
    "GPC": {
        "name":       r"^(.+)\r?\n\s*Teams #",   # line right above "Teams #"
        "project_id": r"Teams #\s*(\d+)",
        "in_service": r"Need Date\s+" + DATE,
        "start_date": r"Start Date\s+" + DATE,
    },
}
FIELDS = ["name", "project_id", "status", "in_service", "start_date", "total_cost"]
BASE = Path(__file__).parent


def parse_page(text):
    for source, patterns in TEMPLATES.items():
        m = re.search(patterns["project_id"], text, re.M)
        if not m:
            continue
        record = {"source": source}
        for field in FIELDS:
            pattern = patterns.get(field)
            m = re.search(pattern, text, re.M | re.S if field == "name" and source == "DESC" else re.M) if pattern else None
            value = " ".join(m.group(1).split()) if m else None
            if field == "total_cost" and value:
                value = int(value.strip("$").replace(",", ""))
            record[field] = value
        return record
    return None


def read_pdf(pdf_path):
    projects, seen = [], set()
    for page_no, text, _ in find_project_pages(f"{BASE}{pdf_path}"):
        record = parse_page(text)
        if record and record["project_id"] not in seen:
            seen.add(record["project_id"])
            projects.append({"page": page_no, **record})
    return projects


if __name__ == "__main__":
    for p in read_pdf("/data/using-data/georgia.pdf"):
        print(p)
