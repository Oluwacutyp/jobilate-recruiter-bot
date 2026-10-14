"""Tests for the live-Jiji-structure fix (2026-10-14).

Verified live against jiji.ng (requests, 1-2 paced fetches, investigation
only): result cards are <a class="... qa-advert-list-item ..."> with
hrefs like /<loc>/<cat>-cvs/<slug>-<id>.html?indexPosition=N. A
0-results page ("0 results for ...") has NO card anchors — only home +
Login/Registration links. The old parser counted Login/Registration as
"cards", and autoscrape aborted the whole vacancy on the FIRST
category's error (farming+Lagos -> 0 results) without ever trying
sales (47 results).

Fixtures here are SYNTHETIC (same shapes, invented text) — tests never
hit live Jiji and never copy real CV content.
"""
import pytest

from jobilate.autoscrape import scrape_one_vacancy
from jobilate.models import Vacancy
from jobilate.scraper import JijiScrapeError, JijiScraper
from jobilate.store import Store

# --- synthetic fixtures (same shapes as live Jiji, invented text) ---

OLD_GENERIC_HTML = """<html><head><title>Seeking Work - CVs</title></head><body>
<a href="https://jiji.ng/some-cv-page">Experienced Sales Person CV</a>
<a href="/another-cv-page">Farm Worker CV</a>
</body></html>"""

NEW_CARD_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head><body>
<div class="b-advert-listing"><div class="masonry-item">
<div class="b-adverts-gallery-listing__item js-advert-list-item">
<a href="/odeda/farming-and-veterinary-cvs/farm-manager-AbC123.html?indexPosition=0"
   class="b-list-advert-base b-list-advert-base--gallery qa-advert-list-item">
₦150,000 - 200,000 Farm Manager Test Farm Ltd Post Held: Fish supervisor
</a></div></div></div>
</body></html>"""

ZERO_RESULTS_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head><body>
<a href="/">Jiji</a>
<a href="/?auth=Login">Sign in</a>
<a href="/?auth=Registration">Registration</a>
<p>0 results for <strong>Seeking Work - CVs</strong> in Nigeria</p>
<p>No results found. Try changing your search.</p>
</body></html>"""

CHALLENGE_SHELL_HTML = """<html><head><title>Just a moment...</title></head><body>
<p>Please verify you are human to continue.</p>
<div id="challenge">checking your browser</div>
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


def _scraper_with_fetcher(fetcher):
    s = JijiScraper(min_delay=0)
    s._fetcher = fetcher
    return s


def test_old_generic_structure_still_parses():
    cards = JijiScraper(min_delay=0).parse_cv_list_html(OLD_GENERIC_HTML)
    assert len(cards) == 2
    assert all(c["cv_url"] for c in cards)


def test_new_card_structure_parses():
    cards = JijiScraper(min_delay=0).parse_cv_list_html(NEW_CARD_HTML)
    assert len(cards) == 1
    assert "farming-and-veterinary-cvs" in cards[0]["cv_url"]
    assert "Farm Manager" in cards[0]["title"]


def test_zero_results_returns_empty_not_error():
    cards = JijiScraper(min_delay=0).parse_cv_list_html(ZERO_RESULTS_HTML)
    assert cards == []  # Login/Registration must NOT count as cards


def test_empty_challenge_page_raises_with_diagnostic():
    # UPDATED 2026-10-14 (Cloudflare fix): a challenge page is now
    # classified as a Cloudflare block, NOT "page structure changed".
    with pytest.raises(JijiScrapeError) as excinfo:
        JijiScraper(min_delay=0).parse_cv_list_html(CHALLENGE_SHELL_HTML)
    msg = str(excinfo.value)
    assert "cloudflare" in msg.lower()
    assert "just a moment" in msg.lower()
    assert "structure changed" not in msg.lower()
    assert "diag:" in msg
    assert "verify-human" in msg
    assert "anchors=0" in msg
    # No full HTML / PII in the message.
    assert "checking your browser" not in msg
    assert len(msg) < 600


def test_autoscrape_continues_after_zero_result_category(tmp_path):
    """First category 0 results -> try next category -> find a match."""
    store = Store(str(tmp_path / "t.db"))
    vid = store.add_vacancy(Vacancy(
        title="Sales Supervisor", location="Lagos State",
        requirements_text="B.Tech 6 years agro-pharma sales",
        education_required="b.tech", min_years=5, status="active"))
    v = store.get_vacancy(vid)

    def fetcher(url):
        if "farming" in url:
            return ZERO_RESULTS_HTML
        if "cvs/" in url and ".html" in url:
            return DETAIL_HTML
        return NEW_CARD_HTML

    links, err = scrape_one_vacancy(store, v, _scraper_with_fetcher(fetcher))
    assert err is None
    assert len(links) == 1


def test_autoscrape_all_zero_results_is_not_an_error(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    vid = store.add_vacancy(Vacancy(title="Sales Supervisor", location="Lagos State", status="active"))
    v = store.get_vacancy(vid)
    links, err = scrape_one_vacancy(store, v, _scraper_with_fetcher(lambda url: ZERO_RESULTS_HTML))
    assert links == [] and err is None


def test_autoscrape_aborts_on_block_error(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    vid = store.add_vacancy(Vacancy(title="Sales Supervisor", location="Lagos State", status="active"))
    v = store.get_vacancy(vid)
    calls = []

    class _BlockScraper:
        def search_url(self, q):
            return "https://example.test/search"

        def fetch(self, url):
            # Fake scraper: fetch raises the block directly (bypassing
            # JijiScraper.fetch, which would convert it to a browser
            # fallback attempt — that is the scraper's own path, tested
            # in test_browser_fetch.py).
            calls.append(url)
            raise JijiScrapeError("Jiji returned a challenge/block page (HTTP 403).")

        def parse_cv_list_html(self, html):
            return []

        def parse_cv_detail_html(self, html, url=""):
            return {}

    links, err = scrape_one_vacancy(store, v, _BlockScraper())
    assert links == [] and err and "403" in err
    assert len(calls) == 1  # aborted, did not hammer other categories


def test_browser_wait_skips_zero_results_pages():
    from jobilate.browser_fetch import _wait_for_cards

    calls = []

    class _FakePage:
        def wait_for_selector(self, sel, timeout):
            calls.append(sel)

        def content(self):
            return "<html>after wait</html>"

    out = _wait_for_cards(_FakePage(), ZERO_RESULTS_HTML)
    assert out == ZERO_RESULTS_HTML
    assert calls == []  # no wait burned on a 0-results page

    out2 = _wait_for_cards(_FakePage(), NEW_CARD_HTML)
    assert out2 == "<html>after wait</html>"
    assert len(calls) == 1
