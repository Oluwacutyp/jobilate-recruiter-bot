"""Mobile fallback + profile-lock + channel-logging + CF_BM tests (2026-10-16).

User-verified bugs:
- Profile lock: "BrowserType.launch_persistent_context: Opening in
  existing browser session ... profile is already in use by another
  instance of Chromium" — a zombie previous scrape locked
  data/browser_profile.
- Silent Chromium fallback: the log showed ms-playwright chromium-1248
  chrome.exe (bundled Chromium), NOT Edge — msedge launch failed and
  it silently fell back to Chromium, which Cloudflare detects more.
- User asked: "Can it use a mobile like browser?" — yes, mobile
  emulation is now an extra fallback (desktop+cookie, desktop,
  mobile+cookie, mobile).

All tests mocked — never hit live Jiji, never launch a real browser,
never contain a real cookie value (fake placeholders only).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.browser_fetch import (
    MOBILE_USER_AGENT,
    _cloudflare_cookies,
    fetch_with_browser,
    read_cf_bm,
)
from jobilate.scraper import JijiScrapeError, JijiScraper

CHALLENGE_HTML = """<html><head><title>Just a moment...</title></head>
<body><h1>Just a moment...</h1><p>Checking your browser.</p>
<p>Cloudflare Ray ID: 1</p><a href="/x">l1</a><a href="/y">l2</a></body></html>"""

REAL_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head>
<body><a class="qa-advert-list-item" href="/lagos/sales-cvs/sales-rep-1.html">Sales Rep</a></body></html>"""


class _FakePage:
    """Page whose content() is driven by its context (see _make_factory)."""

    def __init__(self, ctx):
        self._ctx = ctx

    def goto(self, *a, **k):
        return None

    def content(self):
        return self._ctx.content_for_page()

    def title(self):
        html = self.content()
        if "Just a moment" in html:
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
    def __init__(self, mode, seen):
        self._mode = mode  # "desktop-challenge", "mobile-cookie-challenge", "real", ...
        self._seen = seen
        self.has_cookies = False
        self.user_agent = ""

    def content_for_page(self):
        mode = self._mode
        if mode == "real":
            return REAL_HTML
        if mode == "desktop-challenge":
            return CHALLENGE_HTML if "Pixel 7" not in self.user_agent else REAL_HTML
        if mode == "mobile-cookie-challenge":
            # Mobile + cookie -> still challenged; mobile, no cookie -> passes.
            if "Pixel 7" in self.user_agent and not self.has_cookies:
                return REAL_HTML
            return CHALLENGE_HTML
        return CHALLENGE_HTML

    def new_page(self):
        return _FakePage(self)

    def close(self):
        return None

    def add_init_script(self, script):
        pass

    def add_cookies(self, cookies):
        self.has_cookies = bool(cookies)
        self._seen.setdefault("cookies_calls", []).append(list(cookies))


class _FakeBrowser:
    def __init__(self, mode, seen):
        self._mode = mode
        self._seen = seen

    def new_context(self, **kw):
        self._seen.setdefault("context_uas", []).append(kw.get("user_agent", ""))
        ctx = _FakeCtx(self._mode, self._seen)
        ctx.user_agent = kw.get("user_agent", "")
        ctx.has_touch = kw.get("has_touch")
        ctx.is_mobile = kw.get("is_mobile")
        self._seen.setdefault("context_flags", []).append(
            (kw.get("has_touch"), kw.get("is_mobile"))
        )
        return ctx

    def close(self):
        return None


class _FakeChromium:
    """Fake chromium.launch; launch_persistent_context must never be called."""

    def __init__(self, mode, seen, fail_channels=()):
        self._mode = mode
        self._seen = seen
        self._fail_channels = set(fail_channels)

    def launch(self, **kw):
        channel = kw.get("channel") or "chromium"
        self._seen.setdefault("channels", []).append(channel)
        if channel in self._fail_channels:
            raise RuntimeError(f"simulated launch failure for {channel}")
        return _FakeBrowser(self._mode, self._seen)

    def launch_persistent_context(self, **kw):
        self._seen["persistent_called"] = True
        raise AssertionError("ephemeral context must be used by default")


class _FakePlaywright:
    def __init__(self, mode, seen, fail_channels=()):
        self._mode = mode
        self._seen = seen
        self._fail_channels = fail_channels

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def chromium(self):
        return _FakeChromium(self._mode, self._seen, self._fail_channels)


def _factory(mode, seen, fail_channels=()):
    return lambda: _FakePlaywright(mode, seen, fail_channels)


def test_ephemeral_context_no_profile_lock(tmp_path):
    """Default path must NOT call launch_persistent_context (no lock)."""
    seen: dict = {}
    html = fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=1,
        _playwright_factory=_factory("real", seen),
    )
    assert "qa-advert-list-item" in html
    assert seen.get("persistent_called") is not True
    assert seen.get("channels") == ["msedge"]


def test_channel_fallback_tries_msedge_first_chromium_last_and_error_names_channels(tmp_path):
    """msedge fails -> chrome fails -> Chromium runs; error names channels."""
    seen: dict = {}
    html = fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=1,
        _playwright_factory=_factory("real", seen, fail_channels=("msedge", "chrome")),
    )
    assert "qa-advert-list-item" in html
    assert seen["channels"] == ["msedge", "chrome", "chromium"]

    # All attempts blocked -> final error must name the channels tried.
    seen2: dict = {}
    try:
        fetch_with_browser(
            "https://jiji.ng/seeking-work-cvs?query=x",
            data_dir=str(tmp_path),
            timeout_seconds=1,
            _playwright_factory=_factory("challenge", seen2),
        )
    except JijiScrapeError as exc:
        msg = str(exc)
        assert "channels tried:" in msg
        assert "msedge" in msg
        assert "mobile" in msg  # attempts tried are listed too
    else:
        raise AssertionError("expected JijiScrapeError for always-challenged page")


def test_mobile_fallback_after_desktop_blocked(tmp_path):
    """Desktop Edge blocked -> mobile Pixel 7 pass succeeds."""
    seen: dict = {}
    html = fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=1,
        _playwright_factory=_factory("desktop-challenge", seen),
    )
    assert "qa-advert-list-item" in html
    uas = seen.get("context_uas") or []
    assert uas and "Edg/" in uas[0], "first attempt must be desktop Edge"
    assert any("Pixel 7" in ua for ua in uas), "mobile attempt must happen"
    # Mobile context really is mobile (touch + is_mobile flags).
    flags = seen.get("context_flags") or []
    assert any(f == (True, True) for f in flags)
    assert MOBILE_USER_AGENT.startswith("Mozilla/5.0 (Linux; Android 14; Pixel 7)")


def test_mobile_tries_with_cookie_then_without(tmp_path):
    """Mobile+cookie challenged -> mobile, no cookie, passes."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("CF_CLEARANCE=cf-clearance-TEST\n", encoding="utf-8")
    seen: dict = {}
    html = fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=1,
        dotenv_path=str(dotenv),
        _playwright_factory=_factory("mobile-cookie-challenge", seen),
    )
    assert "qa-advert-list-item" in html
    # Cookie calls: desktop+cookie and mobile+cookie set cookies; the
    # winning mobile attempt must be the one WITHOUT cookies.
    cookie_calls = seen.get("cookies_calls") or []
    assert cookie_calls, "expected at least one cookie injection"
    # Desktop attempts all challenged in this mode, mobile+cookie
    # challenged, so the winning fetch must be mobile without cookies.
    uas = seen.get("context_uas") or []
    mobile_uas = [ua for ua in uas if "Pixel 7" in ua]
    assert len(mobile_uas) >= 2, "mobile must be tried with cookie AND without"


def test_cf_bm_sent_when_present_not_when_absent_never_in_errors(tmp_path):
    """CF_BM (__cf_bm) is optional, sent when present, never in errors."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("CF_CLEARANCE=cf-clearance-TEST\nCF_BM=cf-bm-TEST\n", encoding="utf-8")
    assert read_cf_bm(str(dotenv)) == "cf-bm-TEST"
    cookies = _cloudflare_cookies(str(dotenv), with_cookie=True)
    assert any(c.get("name") == "__cf_bm" and c.get("value") == "cf-bm-TEST" for c in cookies)
    assert any(c.get("name") == "cf_clearance" for c in cookies)

    # Absent -> not sent.
    dotenv2 = tmp_path / ".env2"
    dotenv2.write_text("CF_CLEARANCE=cf-clearance-TEST\n", encoding="utf-8")
    cookies2 = _cloudflare_cookies(str(dotenv2), with_cookie=True)
    assert not any(c.get("name") == "__cf_bm" for c in cookies2)

    # Requests path sends __cf_bm alongside cf_clearance.
    import jobilate.scraper as scraper_mod

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        text = "<html><body>ok</body></html>"

    class _FakeRequests:
        def get(self, url, headers=None, timeout=None):
            captured["headers"] = headers
            return _FakeResp()

    old_requests = scraper_mod.requests
    scraper_mod.requests = _FakeRequests()
    try:
        s = JijiScraper(min_delay=0, dotenv_path=str(dotenv))
        body = s._fetch_requests("https://jiji.ng/seeking-work-cvs?query=x")
        assert "ok" in body
        cookie_hdr = (captured.get("headers") or {}).get("Cookie", "")
        assert "cf_clearance=cf-clearance-TEST" in cookie_hdr
        assert "__cf_bm=cf-bm-TEST" in cookie_hdr
    finally:
        scraper_mod.requests = old_requests

    # Never in errors: a failing factory must not leak either value.
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
        assert "cf-clearance-TEST" not in str(exc)
        assert "cf-bm-TEST" not in str(exc)
    else:
        raise AssertionError("expected JijiScrapeError")
