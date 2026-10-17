"""Cloudflare 'Just a moment...' + Edge + CF_CLEARANCE tests (2026-10-14).

User-verified: same RDP, same IP — real Edge passes Cloudflare, bot's
Playwright Chromium gets "Just a moment...". That is automation
fingerprinting, not IP blocking. All tests mocked — never hit live
Jiji, never launch a real browser, never contain a real cookie.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.browser_fetch import (
    STEALTH_INIT_SCRIPT,
    fetch_with_browser,
    jiji_user_agent,
    read_cf_clearance,
)
from jobilate.scraper import JijiScrapeError, JijiScraper

CHALLENGE_HTML = """<html><head><title>Just a moment...</title></head>
<body><h1>Just a moment...</h1><p>Checking your browser before accessing jiji.ng.</p>
<p>Cloudflare Ray ID: 12345</p>
<a href="/cdn-cgi/challenge">link1</a><a href="/cdn-cgi/challenge">link2</a>
</body></html>"""

REAL_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head>
<body><a class="qa-advert-list-item" href="/lagos/sales-cvs/sales-rep-123.html">Sales Rep</a></body></html>"""


def test_challenge_classified_as_cloudflare_block_not_structure_change():
    s = JijiScraper(min_delay=0)
    try:
        s.parse_cv_list_html(CHALLENGE_HTML)
    except JijiScrapeError as exc:
        msg = str(exc).lower()
        assert "cloudflare" in msg
        assert "just a moment" in msg
        assert "structure changed" not in msg
    else:
        raise AssertionError("expected JijiScrapeError for challenge page")


def test_stealth_init_script_hides_automation():
    assert "webdriver" in STEALTH_INIT_SCRIPT
    assert "undefined" in STEALTH_INIT_SCRIPT
    assert "window.chrome" in STEALTH_INIT_SCRIPT
    assert "plugins" in STEALTH_INIT_SCRIPT
    assert "languages" in STEALTH_INIT_SCRIPT


def test_default_ua_is_edge_not_plain_chrome():
    # Default UA must be Edge (Edg/...) — the cookie was solved in Edge.
    from jobilate.browser_fetch import DEFAULT_USER_AGENT

    assert "Edg/" in DEFAULT_USER_AGENT
    assert "Chrome/" in DEFAULT_USER_AGENT


def test_cf_clearance_never_logged_in_errors(tmp_path):
    secret = "cf-clearance-TEST-SECRET-abc123"
    dotenv = tmp_path / ".env"
    dotenv.write_text(f'CF_CLEARANCE="{secret}"\n', encoding="utf-8")

    def _raising_factory():
        raise RuntimeError("boom")

    try:
        fetch_with_browser(
            "https://jiji.ng/seeking-work-cvs?query=x",
            data_dir=str(tmp_path),
            dotenv_path=str(dotenv),
            _playwright_factory=_raising_factory,
        )
    except JijiScrapeError as exc:
        assert secret not in str(exc)
    else:
        raise AssertionError("expected JijiScrapeError")


def test_cf_clearance_reread_from_dotenv_each_scrape(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("CF_CLEARANCE=first-value\n", encoding="utf-8")
    assert read_cf_clearance(str(dotenv)) == "first-value"
    # User updates .env WITHOUT restarting -> next read sees the new value.
    dotenv.write_text("CF_CLEARANCE=second-value\n", encoding="utf-8")
    assert read_cf_clearance(str(dotenv)) == "second-value"
    # Quoted values are stripped.
    dotenv.write_text('CF_CLEARANCE="quoted-value"\n', encoding="utf-8")
    assert read_cf_clearance(str(dotenv)) == "quoted-value"


def test_browser_uses_msedge_channel_first(tmp_path):
    seen: dict = {}

    class _FakePage:
        def goto(self, *a, **k):
            return None

        def content(self):
            return REAL_HTML

        def title(self):
            return "Seeking Work - CVs in Nigeria"

        def locator(self, *a, **k):
            class _Loc:
                def count(self):
                    return 0

            return _Loc()

        def wait_for_selector(self, *a, **k):
            return True

    class _FakeCtx:
        def new_page(self):
            return _FakePage()

        def close(self):
            return None

        def add_init_script(self, script):
            seen["init_script"] = script

        def add_cookies(self, cookies):
            seen["cookies"] = cookies

    class _FakeBrowser:
        def new_context(self, **kw):
            seen["user_agent"] = kw.get("user_agent")
            return _FakeCtx()

        def close(self):
            return None

    class _FakeChromium:
        def launch(self, **kw):
            seen.setdefault("channels", []).append(kw.get("channel"))
            return _FakeBrowser()

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

    html = fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=5,
        _playwright_factory=lambda: _FakePlaywright(),
    )
    assert "qa-advert-list-item" in html
    # First channel attempted must be msedge (Edge), not chrome.
    assert seen["channels"] and seen["channels"][0] == "msedge"
    # Stealth script applied.
    assert "webdriver" in seen.get("init_script", "")
    # Default UA is Edge.
    assert "Edg/" in (seen.get("user_agent") or "")


def test_cf_clearance_set_in_browser_context(tmp_path):
    secret = "cf-clearance-CTX-TEST-xyz"
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"CF_CLEARANCE={secret}\n", encoding="utf-8")
    seen: dict = {}

    class _FakePage:
        def goto(self, *a, **k):
            return None

        def content(self):
            return REAL_HTML

        def title(self):
            return "Seeking Work - CVs in Nigeria"

        def locator(self, *a, **k):
            class _Loc:
                def count(self):
                    return 0

            return _Loc()

        def wait_for_selector(self, *a, **k):
            return True

    class _FakeCtx:
        def new_page(self):
            return _FakePage()

        def close(self):
            return None

        def add_init_script(self, script):
            pass

        def add_cookies(self, cookies):
            seen["cookies"] = cookies

    class _FakeBrowser:
        def new_context(self, **kw):
            return _FakeCtx()

        def close(self):
            return None

    class _FakeChromium:
        def launch(self, **kw):
            return _FakeBrowser()

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

    fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=5,
        dotenv_path=str(dotenv),
        _playwright_factory=lambda: _FakePlaywright(),
    )
    cookies = seen.get("cookies") or []
    assert cookies, "expected CF_CLEARANCE cookies in browser context"
    assert any(c.get("name") == "cf_clearance" for c in cookies)
    # Cookie value present in the context call (as it must be to work),
    # but never in any error message — covered by test_cf_clearance_never_logged.
    assert any(c.get("domain") == ".jiji.ng" for c in cookies)


def test_browser_waits_for_challenge_to_clear(tmp_path):
    """Challenge HTML first, then real HTML -> fetch returns real HTML.

    Simulates Cloudflare's automatic 'Just a moment...' check clearing
    after a couple of polls (real Edge + time). No real browser.
    """
    calls = {"n": 0}

    class _FakePage:
        def goto(self, *a, **k):
            return None

        def content(self):
            calls["n"] += 1
            if calls["n"] <= 2:
                return CHALLENGE_HTML
            return REAL_HTML

        def title(self):
            if calls["n"] <= 2:
                return "Just a moment..."
            return "Seeking Work - CVs in Nigeria"

        def locator(self, *a, **k):
            class _Loc:
                def count(self):
                    return 0

            return _Loc()

        def wait_for_selector(self, *a, **k):
            return True

        class _Mouse:
            def move(self, *a, **k):
                return None

            def wheel(self, *a, **k):
                return None

        @property
        def mouse(self):
            return self._Mouse()

    class _FakeCtx:
        def new_page(self):
            return _FakePage()

        def close(self):
            return None

        def add_init_script(self, script):
            pass

        def add_cookies(self, cookies):
            pass

    class _FakeBrowser:
        def new_context(self, **kw):
            return _FakeCtx()

        def close(self):
            return None

    class _FakeChromium:
        def launch(self, **kw):
            return _FakeBrowser()

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

    html = fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=10,
        _playwright_factory=lambda: _FakePlaywright(),
    )
    assert "qa-advert-list-item" in html
    assert calls["n"] >= 3, "expected polling until challenge cleared"


def test_jiji_user_agent_env_override(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("JIJI_USER_AGENT=CustomUA/1.0 Edg/1.0\n", encoding="utf-8")
    assert jiji_user_agent(str(dotenv)) == "CustomUA/1.0 Edg/1.0"
