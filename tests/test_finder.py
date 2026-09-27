"""Plan finder: link extraction, ranking, and URL safety (no network needed)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finder  # noqa: E402

# trimmed copy of the real SCRTP homepage links
SCRTP_HTML = """
<a href="/assets/pdfs/home/ceii-nda.pdf">CEII-NDA (PDF)</a>
<a href="/assets/pdfs/ferc-orders/ferc-order-1000.pdf">FERC Order No. 1000</a>
<a href="/assets/pdfs/home/attachment-k-dominion-energy.pdf">Dominion Energy (Attachment K)</a>
<a href="/assets/pdfs/home/2026-2030-2million-and-above-project-descriptions.pdf"><span>$2M &amp; Above Project Descriptions</span></a>
<a href="/about">About</a>
"""


class FakeResponse:
    text = SCRTP_HTML


class FakeClient:
    def get(self, url):
        return FakeResponse()


def test_pdf_links_resolves_relative_urls_and_ignores_pages():
    links = finder.pdf_links(SCRTP_HTML, "https://www.scrtp.com/")
    assert len(links) == 4
    assert links[3] == {
        "url": "https://www.scrtp.com/assets/pdfs/home/2026-2030-2million-and-above-project-descriptions.pdf",
        "title": "$2M & Above Project Descriptions"}


def test_project_list_ranks_first_for_dominion():
    found = finder.search_portals("Dominion Energy South Carolina", FakeClient())
    best = max(found, key=lambda c: c["score"])
    assert "project-descriptions" in best["url"]
    ferc = next(c for c in found if "ferc-order" in c["url"])
    assert ferc["score"] < 0


def test_portals_only_searched_for_their_utilities():
    assert finder.search_portals("Pacific Gas and Electric", FakeClient()) == []


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x.pdf", "http://localhost:8000/api", "http://169.254.169.254/latest",
    "http://10.0.0.5/plan.pdf", "file:///etc/passwd", "ftp://example.com/a.pdf",
])
def test_rejects_internal_and_non_http_urls(url):
    with pytest.raises(ValueError):
        finder.check_public_url(url)


def test_known_docs_generate_fpl_filings():
    found = finder.search_known("FPL")
    urls = [c["url"] for c in found]
    assert any("TenYearSitePlans" in u and "Florida%20Power%20and%20Light%20Company" in u for u in urls)
    assert any("fpl.com" in u for u in urls)
    assert finder.search_known("Florida Power & Light")  # full name works too
    assert finder.search_known("Georgia Power") == []    # no false matches


def test_unverified_guesses_are_dropped(monkeypatch):
    monkeypatch.setattr(finder, "search_portals", lambda n, c: [])
    monkeypatch.setattr(finder, "search_gemini", lambda n, s, c, e: [])
    monkeypatch.setattr(finder, "probe", lambda url, c: ("2026" in url and "floridapsc" in url, 3.1))
    result = finder.find_plans("FPL", "FL")
    assert [c["title"] for c in result["candidates"]] == ["FPL Ten Year Site Plan 2026"]
    assert result["candidates"][0]["verified"] is True


def test_known_docs_carry_the_state():
    assert {c["state"] for c in finder.search_known("FPL")} == {"FL"}
