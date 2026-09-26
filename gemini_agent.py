import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

from page_detect import find_project_pages

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")


class Project(BaseModel):
    source_page: int
    project_id: str | None
    name: str
    endpoint_a: str | None
    endpoint_b: str | None
    voltage_kv: int | None
    status: str | None
    in_service_date: str | None
    start_date: str | None
    total_cost: int | None


class Endpoints(BaseModel):
    index: int
    endpoint_a: str | None
    endpoint_b: str | None


EXTRACT_PROMPT = """You extract planned electric transmission projects from utility filings.

Pages are marked "=== PAGE n ===". Return one entry per planned project on these pages.

Rules:
- Only use values that literally appear in the text. Never guess.
- Use null for anything missing, blank, or REDACTED.
- source_page = the page number the project appears on.
- project_id = the utility's own ID (e.g. "Project ID", "Teams #", "TEAMS Number").
- name = the full project name. Table rows can wrap onto several lines; join the pieces.
- endpoint_a / endpoint_b = the two substations a line connects, taken from the name
  (e.g. "EVANS PRIMARY - THOMSON PRIMARY 115KV REBUILD" -> "EVANS PRIMARY", "THOMSON PRIMARY").
  A project at a single substation has endpoint_b null. Drop voltages and work descriptions.
- voltage_kv = the highest voltage in kV, as an integer.
- in_service_date = planned in-service or need date. start_date = construction start date.
  Format both as YYYY-MM-DD.
- total_cost = total estimated cost in whole dollars, as an integer.
- Skip cancelled or completed projects, table headers, and anything that is not a planned project.
"""

SPLIT_PROMPT = """For each numbered transmission project name, return the two substations it connects.
Use the exact spelling from the name. Drop voltages (115KV, 230 kV), prefixes like "SAV:" or "GTC:",
and work words (REBUILD, RECONDUCTOR, CONSTRUCT, ...). If the project is at a single substation,
endpoint_b is null. If there is no substation name, both are null. Return the index you were given.
"""


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _iso_date(value):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            pass
    return None


class GeminiAgent:
    def __init__(self, api_key=None, model=None, pages_per_call=5, names_per_call=60,
                 request_gap=4.0, cache_dir=BASE / "gemini_cache"):
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        self.pages_per_call = pages_per_call
        self.names_per_call = names_per_call
        self.request_gap = request_gap
        self.cache_dir = Path(cache_dir)

    def extract_projects(self, pdf_path, progress=None):
        """Extract every planned project from any utility PDF. Cached by file hash."""
        cache = self._cache_path(pdf_path)
        if cache.exists():
            return json.loads(cache.read_text())

        pages = find_project_pages(str(pdf_path))
        n = self.pages_per_call
        batches = [pages[i:i + n] for i in range(0, len(pages), n)]
        results, seen = [], set()

        for b, batch in enumerate(batches, 1):
            page_nums = [num for num, _, _ in batch]
            batch_text = "\n\n".join(f"=== PAGE {num} ===\n{t[:8000]}" for num, t, _ in batch)

            for p in self._generate(EXTRACT_PROMPT + "\n\n" + batch_text, list[Project]):
                rec = p.model_dump()
                if not self._grounded(rec, batch_text):
                    continue
                if rec["source_page"] not in page_nums:
                    rec["source_page"] = page_nums[0]
                rec["in_service_date"] = _iso_date(rec["in_service_date"])
                rec["start_date"] = _iso_date(rec["start_date"])
                key = rec["project_id"] or rec["name"].upper()
                if key not in seen:
                    seen.add(key)
                    results.append(rec)

            if progress:
                progress(b, len(batches))
            if b < len(batches):
                time.sleep(self.request_gap)

        self.cache_dir.mkdir(exist_ok=True)
        cache.write_text(json.dumps(results, indent=2))
        return results

    def split_endpoints(self, records):
        """Fill endpoint_a / endpoint_b from each record's name. Returns the same list."""
        todo = [r for r in records if r.get("name") and not r.get("endpoint_a")]
        n = self.names_per_call
        chunks = [todo[i:i + n] for i in range(0, len(todo), n)]

        for c, chunk in enumerate(chunks, 1):
            prompt = SPLIT_PROMPT + "\n\n" + "\n".join(f"{i}. {r['name']}" for i, r in enumerate(chunk))
            for e in self._generate(prompt, list[Endpoints]):
                if not 0 <= e.index < len(chunk):
                    continue
                rec = chunk[e.index]
                name = _squash(rec["name"])
                for field in ("endpoint_a", "endpoint_b"):
                    value = getattr(e, field)
                    ok = value and _squash(value) and _squash(value) in name
                    rec[field] = value.strip() if ok else None
            if c < len(chunks):
                time.sleep(self.request_gap)

        for r in records:
            r.setdefault("endpoint_a", None)
            r.setdefault("endpoint_b", None)
        return records

    def _generate(self, prompt, schema, retries=5):
        for attempt in range(retries):
            try:
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0,
                    ),
                )
                return resp.parsed or []
            except Exception as e:
                code = getattr(e, "code", None)
                if code in (429, 500, 503) and attempt < retries - 1:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise

    @staticmethod
    def _grounded(rec, source_text):
        """Drop anything made up: the ID and every word of the name must be in the source."""
        text = _squash(source_text)
        if rec.get("project_id") and _squash(rec["project_id"]) not in text:
            return False
        words = [w for w in re.findall(r"[a-z0-9]+", rec["name"].lower()) if len(w) > 1]
        return bool(words) and all(w in text for w in words)

    def _cache_path(self, pdf_path):
        digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()[:16]
        return self.cache_dir / f"{digest}_{self.model}.json"