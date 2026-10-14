"""Tests for the global cross-category catch-all pass (2026-10-14).

Gap (user-spotted): category-limited search misses qualified candidates
posted outside the expected categories — e.g. a B.Tech + 5y
vet-drug-sales CV posted under "Management" or "General" for a
"Sales Supervisor" vacancy. Matching is already category-agnostic
(scores by education/years/skills/location), so the fix is a global
search pass AFTER the category passes: query = title + location, NO
category, same cap, same dedup, same scoring.

All tests are mocked — never hit live Jiji.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.autoscrape import (
    build_global_search_query,
    scrape_one_vacancy,
)
from jobilate.models import Vacancy
from jobilate.store import Store

TITLE = "Sales Supervisor"
LOCATION = "Lagos State"
GLOBAL_QUERY = "Sales Supervisor Lagos State"
CAT_FARMING = "Sales Supervisor farming & veterinary Lagos State"
CAT_SALES = "Sales Supervisor sales Lagos State"
CAT_ADVERTISING = "Sales Supervisor advertising & marketing Lagos State"

ZERO_RESULTS_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head><body>
<a href="/">Jiji</a>
<a href="/?auth=Login">Sign in</a>
<p>0 results for <strong>Seeking Work - CVs</strong> in Nigeria</p>
<p>No results found. Try changing your search.</p>
</body></html>"""

# Card posted under "Management" — OUTSIDE the expected categories for
# Sales Supervisor (farming & veterinary / sales / advertising).
GLOBAL_CARD_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head><body>
<a href="/lagos/management-cvs/sales-manager-Global1.html?indexPosition=0"
   class="qa-advert-list-item">Sales Manager Global Candidate</a>
</body></html>"""

SHARED_CARD_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head><body>
<a href="/lagos/sales-cvs/sales-representative-Shared1.html?indexPosition=0"
   class="qa-advert-list-item">Sales Representative Shared Candidate</a>
</body></html>"""

DETAIL_HTML = """<html><head><title>Sales Representative CV</title></head><body>
<h1>Sales Representative — Vet Products</h1>
<p>Job Type: Full-Time</p>
<p>Education: B.Tech Animal Production</p>
<p>Skills: vet drug sales</p>
<p>Previous Work Experience: 6 years agro-pharma sales</p>
<p>Expected Salary: ₦400,000</p>
<p>Location: Lagos State</p>
</body></html>"""


def _cards_html(prefix: str, n: int) -> str:
    anchors = "".join(
        f'<a href="/lagos/x-cvs/{prefix}-{i}.html" class="qa-advert-list-item">'
        f"{prefix} Candidate {i}</a>"
        for i in range(n)
    )
    return f"<html><head><title>Seeking Work - CVs</title></head><body>{anchors}</body></html>"


class _MockScraper:
    """Mock scraper: search_url records queries + returns query as URL.

    fetch treats a string containing '.html' as a detail page, anything
    else as a search query (exact-match dispatch in each test).
    """

    def __init__(self, list_by_query: dict):
        self.list_by_query = list_by_query
        self.queries: list[str] = []
        self.detail_fetches: list[str] = []

    def search_url(self, q):
        self.queries.append(q)
        return q  # query itself is the "URL" for fetch dispatch

    def fetch(self, url):
        if ".html" in url:
            self.detail_fetches.append(url)
            return DETAIL_HTML
        return self.list_by_query.get(url, ZERO_RESULTS_HTML)

    def parse_cv_list_html(self, html):
        # Use the REAL parser so card shapes / 0-results are exercised.
        from jobilate.scraper import JijiScraper

        return JijiScraper(min_delay=0).parse_cv_list_html(html)

    def parse_cv_detail_html(self, html, url=""):
        from jobilate.scraper import JijiScraper

        return JijiScraper(min_delay=0).parse_cv_detail_html(html, url)


def _vacancy(store: Store):
    vid = store.add_vacancy(
        Vacancy(
            title=TITLE,
            location=LOCATION,
            requirements_text="B.Tech 6 years agro-pharma sales",
            education_required="b.tech",
            min_years=5,
            status="active",
        )
    )
    return store.get_vacancy(vid)


def test_global_only_candidate_is_found_and_scored(tmp_path):
    """Candidate present ONLY in the global pass is returned + scored."""
    store = Store(str(tmp_path / "t.db"))
    v = _vacancy(store)
    scraper = _MockScraper({GLOBAL_QUERY: GLOBAL_CARD_HTML})
    links, err = scrape_one_vacancy(store, v, scraper)
    assert err is None
    assert len(links) == 1
    # Global query was actually issued (after the category passes).
    assert GLOBAL_QUERY in scraper.queries
    # Scored (not just stored): Tier + reason present.
    assert links[0].get("tier") in ("Tier1", "Tier2", "Tier3")
    assert links[0].get("match_reason")


def test_candidate_in_both_category_and_global_is_deduped(tmp_path):
    """Same cv_url in category + global appears once, not twice."""
    store = Store(str(tmp_path / "t.db"))
    v = _vacancy(store)
    scraper = _MockScraper(
        {CAT_SALES: SHARED_CARD_HTML, GLOBAL_QUERY: SHARED_CARD_HTML}
    )
    links, err = scrape_one_vacancy(store, v, scraper)
    assert err is None
    assert len(links) == 1
    # Detail fetched once (global duplicate never reached the detail loop).
    assert len(scraper.detail_fetches) == 1


def test_global_pass_skipped_when_cap_already_reached(tmp_path):
    """Category passes already at max_cards -> global pass never runs."""
    store = Store(str(tmp_path / "t.db"))
    v = _vacancy(store)
    scraper = _MockScraper({CAT_SALES: SHARED_CARD_HTML, GLOBAL_QUERY: GLOBAL_CARD_HTML})
    links, err = scrape_one_vacancy(store, v, scraper, max_cards=1)
    assert err is None
    assert len(links) == 1
    assert GLOBAL_QUERY not in scraper.queries


def test_global_pass_counts_toward_same_cap(tmp_path):
    """Category 12 + global 20 with cap 20 -> 20 links, NOT 32."""
    store = Store(str(tmp_path / "t.db"))
    v = _vacancy(store)
    scraper = _MockScraper(
        {
            CAT_FARMING: _cards_html("cat", 12),
            GLOBAL_QUERY: _cards_html("global", 20),
        }
    )
    links, err = scrape_one_vacancy(store, v, scraper, max_cards=20)
    assert err is None
    assert len(links) == 20


def test_global_query_is_title_plus_location_no_category(tmp_path):
    """Global query = title + location, no category token."""
    assert build_global_search_query(TITLE, LOCATION) == GLOBAL_QUERY
    assert "farming" not in build_global_search_query(TITLE, LOCATION)
    assert "advertising" not in build_global_search_query(TITLE, LOCATION)
    # And the scrape actually issues it (not just the helper existing).
    store = Store(str(tmp_path / "t.db"))
    v = _vacancy(store)
    scraper = _MockScraper({})
    links, err = scrape_one_vacancy(store, v, scraper)
    assert err is None and links == []
    assert GLOBAL_QUERY in scraper.queries
    for q in scraper.queries:
        assert len(q) <= 120
