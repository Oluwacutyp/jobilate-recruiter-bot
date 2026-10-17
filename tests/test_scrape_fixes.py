"""Fixes for two user-verified blocking bugs (2026-10-14):
1. Playwright Sync API called inside the asyncio loop.
2. Full vacancy text saved as title -> giant search URL + giant error bubble.
All tests are mocked — never hit real Jiji, never launch a real browser."""
import asyncio
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.autoscrape import build_search_query, scrape_one_vacancy, short_search_title
from jobilate.browser_fetch import fetch_with_browser, fetch_with_browser_async
from jobilate.models import Vacancy
from jobilate.scraper import JijiScrapeError, JijiScraper, truncate_url
from jobilate.store import Store
from jobilate.vacancy_parser import parse_vacancy_text

FULL_PASTE = """JOB VACANCY: SALES SUPERVISOR

Industry: Agro-Pharmaceuticals
Location: Lagos State
Salary: ₦500,000+monthly
Employment Type: Full-Time

Requirements:

* Education (Mandatory): B.Tech, B.Agric, HND in Animal Production and Health, or B.Sc. in Animal Health Technology.
* Minimum of 5 years' verifiable experience in agro-pharmaceutical sales, particularly veterinary drugs.
* Strong industry connections with feed millers, commercial farms, agro-dealers, and distributors.
* Proven sales, business development, and team leadership skills.
* Willingness to travel when required.

Key Responsibilities:

* Drive sales and develop new markets.
* Manage key clients and maintain business relationships.
* Supervise sales representatives and achieve sales targets.
* Monitor market trends and prepare sales reports.
"""


def test_fetch_async_no_sync_in_async_error():
    """Async fetch path must NOT raise 'Sync API inside asyncio loop'.

    The fake browser simulates Playwright's Sync API: it raises if called
    on a thread with a running event loop, and succeeds in a worker
    thread (where asyncio.to_thread runs it).
    """

    def fake_requests(url):
        return "challenge cloudflare verify you are human"

    def fake_browser(url):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return "<html><body>ok</body></html>"
        raise RuntimeError(
            "It looks like you are using Playwright Sync API inside the asyncio loop. "
            "Please use the Async API instead."
        )

    s = JijiScraper(min_delay=0, _fetcher=fake_requests, browser_fetcher=fake_browser)
    result = asyncio.run(s.fetch_async("https://jiji.ng/seeking-work-cvs?query=x"))
    assert result == "<html><body>ok</body></html>"


def test_fetch_with_browser_async_no_sync_in_async_error():
    """Direct browser async wrapper also runs sync Playwright off-loop."""

    def fake_factory():
        raise AssertionError("must not be called - to_thread fake below replaces fetch")

    # Use fetch_with_browser_async with an injected factory that checks
    # for a running loop, by monkeypatching the sync fetch's factory path:
    # simplest is to pass a factory that returns a fake playwright whose
    # context manager asserts no running loop.
    import asyncio as _asyncio

    class _FakePage:
        def goto(self, *a, **k):
            return None

        def content(self):
            return "<html><body>ok</body></html>"

        def locator(self, *a, **k):
            class _Loc:
                def count(self):
                    return 0

            return _Loc()

    class _FakeCtx:
        def new_page(self):
            return _FakePage()

        def close(self):
            return None

    class _FakeBrowser:
        def new_context(self, **kw):
            return _FakeCtx()

        def close(self):
            return None

    class _FakeChromium:
        def launch(self, **kw):
            try:
                _asyncio.get_running_loop()
            except RuntimeError:
                return _FakeBrowser()
            raise RuntimeError("Sync API inside asyncio loop")

        def launch_persistent_context(self, **kw):
            raise AssertionError("ephemeral context must be used by default")

    class _FakePlaywright:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @property
        def chromium(self):
            return _FakeChromium()

    result = asyncio.run(
        fetch_with_browser_async(
            "https://jiji.ng/seeking-work-cvs?query=x",
            data_dir="/tmp",
            _playwright_factory=lambda: _FakePlaywright(),
        )
    )
    assert "ok" in result


def test_search_url_truncates_long_queries():
    s = JijiScraper(min_delay=0)
    url = s.search_url("x" * 500)
    assert "x" * 200 not in url
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
    assert len(q) <= 150


def test_scrape_builds_short_query_from_multiline_title(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    # Simulate the corrupted vacancy: title = FULL pasted vacancy text.
    vid = store.add_vacancy(Vacancy(title=FULL_PASTE, location="Lagos State", status="active"))
    v = store.get_vacancy(vid)

    class _RecordingScraper:
        def __init__(self):
            self.queries = []

        def search_url(self, q):
            self.queries.append(q)
            return "https://example.test/search"

        def fetch(self, url):
            return "html"

        def parse_cv_list_html(self, html):
            return []

        def parse_cv_detail_html(self, html, url=""):
            return {}

    scraper = _RecordingScraper()
    links, err = scrape_one_vacancy(store, v, scraper)
    assert err is None
    assert links == []
    assert scraper.queries, "expected at least one search query"
    for q in scraper.queries:
        assert len(q) <= 120, f"query too long: {len(q)}"
        assert "sales supervisor" in q.lower()
        assert "key responsibilities" not in q.lower()
        assert "requirements" not in q.lower() or "key" not in q.lower()


def test_parser_title_single_line_max_120():
    parsed = parse_vacancy_text(FULL_PASTE)
    assert parsed["title"] == "Sales Supervisor"
    assert "\n" not in parsed["title"]
    assert len(parsed["title"]) <= 120
    assert parsed["min_years"] == 5
    # A single-line overlong title is truncated, never stored whole.
    parsed2 = parse_vacancy_text("A" * 500)
    assert len(parsed2["title"]) <= 120
    assert "\n" not in parsed2["title"]


def test_error_messages_truncate_urls():
    long_url = "https://jiji.ng/seeking-work-cvs?query=" + "JOB+VACANCY%3A+SALES+SUPERVISOR" * 20
    assert len(truncate_url(long_url)) <= 123
    assert truncate_url(long_url).endswith("...")
    assert "SALES+SUPERVISOR" * 5 not in truncate_url(long_url)

    def _raising_factory():
        raise RuntimeError("boom " + "x" * 1000)

    try:
        fetch_with_browser(long_url, _playwright_factory=_raising_factory)
    except JijiScrapeError as exc:
        msg = str(exc)
        assert len(msg) <= 500, f"error message too long: {len(msg)}"
        assert long_url not in msg
        # The 1000-char cause is truncated to 300 chars in the message.
        assert msg.count("x") < 1000
    else:
        raise AssertionError("expected JijiScrapeError")

    # Short-query helper itself caps at 120.
    assert len(build_search_query(FULL_PASTE, "farming & veterinary", "Lagos State")) <= 120
    assert "key responsibilities" not in build_search_query(
        FULL_PASTE, "farming & veterinary", "Lagos State"
    ).lower()
