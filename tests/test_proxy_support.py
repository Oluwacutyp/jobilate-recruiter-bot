"""Residential proxy (PROXY_URL) tests (2026-10-17).

User-verified: fresh CF_CLEARANCE + mobile fallback STILL blocked
(2026-10-15/16) — root cause is IP reputation (AWS datacenter IP).
The durable fix is a residential IP via PROXY_URL.

All tests mocked — never hit live Jiji, never launch a real browser,
never use a real proxy, never contain a real credential (fake
placeholders only). The proxy password placeholder is checked to
NEVER appear in logs, status dicts, /config lines, or errors.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.browser_fetch import (
    fetch_with_browser,
    proxy_config_line,
    proxy_status,
    read_proxy_url,
    requests_proxies,
)
from jobilate.scraper import JijiScrapeError, JijiScraper

FAKE_PROXY = "http://proxyuser:proxypass-TEST@proxy.example:8080"
FAKE_PROXY_SOCKS = "socks5://proxyuser:proxypass-TEST@proxy.example:1080"


def _write_env(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_proxy_url_set_requests_uses_proxies_and_never_logs_url(tmp_path, caplog):
    """PROXY_URL set -> requests gets proxies dict; URL never in logs."""
    dotenv = _write_env(tmp_path, ".env", f"PROXY_URL={FAKE_PROXY}\n")
    assert read_proxy_url(dotenv) == FAKE_PROXY
    proxies = requests_proxies(dotenv)
    assert proxies == {"http": FAKE_PROXY, "https": FAKE_PROXY}

    import jobilate.scraper as scraper_mod

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        text = "<html><body>ok</body></html>"

    class _FakeRequests:
        def get(self, url, **kw):
            captured["kwargs"] = kw
            return _FakeResp()

    old_requests = scraper_mod.requests
    scraper_mod.requests = _FakeRequests()
    try:
        with caplog.at_level(logging.DEBUG):
            s = JijiScraper(min_delay=0, dotenv_path=dotenv)
            assert "ok" in s._fetch_requests("https://jiji.ng/seeking-work-cvs?query=x")
        assert captured["kwargs"]["proxies"] == {"http": FAKE_PROXY, "https": FAKE_PROXY}
    finally:
        scraper_mod.requests = old_requests
    assert "proxypass-TEST" not in caplog.text
    assert "proxyuser" not in caplog.text


def test_proxy_url_aliases_and_precedence(tmp_path, monkeypatch):
    """HTTP_PROXY/HTTPS_PROXY work as aliases; PROXY_URL wins."""
    # The sandbox itself exports HTTP_PROXY — clear it so file values decide.
    for key in ("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(key, raising=False)
    dotenv = _write_env(tmp_path, ".env", "HTTP_PROXY=http://http-proxy.example:8080\n")
    assert read_proxy_url(dotenv) == "http://http-proxy.example:8080"

    dotenv2 = _write_env(tmp_path, ".env2", "HTTPS_PROXY=https://https-proxy.example:8443\n")
    assert read_proxy_url(dotenv2) == "https://https-proxy.example:8443"

    dotenv3 = _write_env(
        tmp_path, ".env3",
        f"PROXY_URL={FAKE_PROXY}\nHTTP_PROXY=http://http-proxy.example:8080\n",
    )
    assert read_proxy_url(dotenv3) == FAKE_PROXY  # PROXY_URL wins

    # Scheme-less value gets http:// prepended; socks5 passes through.
    dotenv4 = _write_env(tmp_path, ".env4", "PROXY_URL=proxy.example:8080\n")
    assert read_proxy_url(dotenv4) == "http://proxy.example:8080"
    dotenv5 = _write_env(tmp_path, ".env5", f"PROXY_URL={FAKE_PROXY_SOCKS}\n")
    assert read_proxy_url(dotenv5) == FAKE_PROXY_SOCKS
    assert requests_proxies(dotenv5) == {"http": FAKE_PROXY_SOCKS, "https": FAKE_PROXY_SOCKS}


def test_proxy_not_set_requests_direct_unchanged(tmp_path, monkeypatch):
    """No PROXY_URL -> requests called WITHOUT a proxies kwarg (as before)."""
    for key in ("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(key, raising=False)
    dotenv = _write_env(tmp_path, ".env", "CF_CLEARANCE=cf-clearance-TEST\n")
    assert read_proxy_url(dotenv) == ""
    assert requests_proxies(dotenv) is None

    import jobilate.scraper as scraper_mod

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        text = "<html><body>ok</body></html>"

    class _FakeRequests:
        def get(self, url, headers=None, timeout=None):
            captured["kwargs"] = {"headers": headers, "timeout": timeout}
            return _FakeResp()

    old_requests = scraper_mod.requests
    scraper_mod.requests = _FakeRequests()
    try:
        s = JijiScraper(min_delay=0, dotenv_path=dotenv)
        assert "ok" in s._fetch_requests("https://jiji.ng/seeking-work-cvs?query=x")
        assert "proxies" not in captured["kwargs"]
    finally:
        scraper_mod.requests = old_requests


def test_proxy_connection_error_falls_back_to_direct_once(tmp_path):
    """Proxy down (ConnectionError) -> ONE direct retry, returns body."""
    dotenv = _write_env(tmp_path, ".env", f"PROXY_URL={FAKE_PROXY}\n")

    import jobilate.scraper as scraper_mod

    calls: list = []

    class _FakeResp:
        status_code = 200
        text = "<html><body>direct-ok</body></html>"

    class _FakeRequests:
        def get(self, url, **kw):
            calls.append(kw)
            if "proxies" in kw:
                raise ConnectionError("proxy down (simulated)")
            return _FakeResp()

    old_requests = scraper_mod.requests
    scraper_mod.requests = _FakeRequests()
    try:
        s = JijiScraper(min_delay=0, dotenv_path=dotenv)
        assert "direct-ok" in s._fetch_requests("https://jiji.ng/seeking-work-cvs?query=x")
    finally:
        scraper_mod.requests = old_requests
    assert len(calls) == 2  # proxy attempt + ONE direct retry
    assert "proxies" in calls[0]
    assert "proxies" not in calls[1]


def test_proxy_407_falls_back_to_direct_without_reusing_proxy(tmp_path):
    """Proxy returns 407 (auth) -> fall back to direct, never retry via proxy."""
    dotenv = _write_env(tmp_path, ".env", f"PROXY_URL={FAKE_PROXY}\n")

    import jobilate.scraper as scraper_mod

    calls: list = []

    class _ProxyResp:
        status_code = 407
        text = "Proxy Authentication Required"

    class _DirectResp:
        status_code = 200
        text = "<html><body>direct-ok</body></html>"

    class _FakeRequests:
        def get(self, url, **kw):
            calls.append(kw)
            return _ProxyResp() if "proxies" in kw else _DirectResp()

    old_requests = scraper_mod.requests
    scraper_mod.requests = _FakeRequests()
    try:
        s = JijiScraper(min_delay=0, dotenv_path=dotenv)
        assert "direct-ok" in s._fetch_requests("https://jiji.ng/seeking-work-cvs?query=x")
    finally:
        scraper_mod.requests = old_requests
    assert len(calls) == 2
    assert "proxies" in calls[0]
    assert "proxies" not in calls[1]


# ---- Playwright fakes (same shape as test_mobile_fallback.py) ----

REAL_HTML = """<html><head><title>Seeking Work - CVs in Nigeria</title></head>
<body><a class="qa-advert-list-item" href="/lagos/sales-cvs/sales-rep-1.html">Sales Rep</a></body></html>"""


class _FakePage:
    def __init__(self, ctx):
        self._ctx = ctx

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
        return _FakePage(self)

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
    def __init__(self, seen, fail_with_proxy=False):
        self._seen = seen
        self._fail_with_proxy = fail_with_proxy

    def launch(self, **kw):
        self._seen.setdefault("launch_kwargs", []).append(dict(kw))
        if self._fail_with_proxy and "proxy" in kw:
            raise RuntimeError("simulated proxy launch failure")
        return _FakeBrowser()

    def launch_persistent_context(self, **kw):
        raise AssertionError("ephemeral context must be used by default")


class _FakePlaywright:
    def __init__(self, seen, fail_with_proxy=False):
        self._seen = seen
        self._fail_with_proxy = fail_with_proxy

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def chromium(self):
        return _FakeChromium(self._seen, self._fail_with_proxy)


def test_playwright_launch_passes_proxy_server(tmp_path, caplog):
    """Browser launch gets proxy={server} — credentials never in logs."""
    dotenv = _write_env(tmp_path, ".env", f"PROXY_URL={FAKE_PROXY}\n")
    seen: dict = {}
    with caplog.at_level(logging.DEBUG):
        html = fetch_with_browser(
            "https://jiji.ng/seeking-work-cvs?query=x",
            data_dir=str(tmp_path),
            timeout_seconds=1,
            dotenv_path=dotenv,
            _playwright_factory=lambda: _FakePlaywright(seen),
        )
    assert "qa-advert-list-item" in html
    launches = seen.get("launch_kwargs") or []
    assert launches, "expected at least one browser launch"
    assert launches[0].get("proxy") == {"server": FAKE_PROXY}
    assert "proxypass-TEST" not in caplog.text
    assert "proxyuser" not in caplog.text


def test_playwright_proxy_failure_falls_back_to_direct(tmp_path):
    """Proxy launch fails -> ONE direct launch (no proxy) succeeds."""
    dotenv = _write_env(tmp_path, ".env", f"PROXY_URL={FAKE_PROXY}\n")
    seen: dict = {}
    html = fetch_with_browser(
        "https://jiji.ng/seeking-work-cvs?query=x",
        data_dir=str(tmp_path),
        timeout_seconds=1,
        dotenv_path=dotenv,
        _playwright_factory=lambda: _FakePlaywright(seen, fail_with_proxy=True),
    )
    assert "qa-advert-list-item" in html
    launches = seen.get("launch_kwargs") or []
    # Proxy passes fail across channels, then the direct pass succeeds.
    assert any("proxy" in kw for kw in launches), "proxy launch must be tried"
    assert launches[-1].get("proxy") is None, "final launch must be direct"
    assert "proxies" not in str(launches[-1])


def test_config_shows_proxy_host_only_never_password(tmp_path, monkeypatch):
    """proxy_status + /config line show host only, never credentials."""
    for key in ("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(key, raising=False)
    dotenv = _write_env(tmp_path, ".env", f"PROXY_URL={FAKE_PROXY}\n")
    st = proxy_status(dotenv)
    assert st == {"set": True, "host": "proxy.example", "scheme": "http", "source": ".env file"}
    assert "proxypass-TEST" not in str(st)
    assert "proxyuser" not in str(st)
    line = proxy_config_line(dotenv)
    assert "proxy.example" in line
    assert "proxypass-TEST" not in line
    assert "proxyuser" not in line

    # Not set -> NOT SET line.
    dotenv2 = _write_env(tmp_path, ".env2", "CF_CLEARANCE=cf-clearance-TEST\n")
    st2 = proxy_status(dotenv2)
    assert st2["set"] is False
    assert "NOT SET" in proxy_config_line(dotenv2)

    # A browser error must never contain the proxy password either.
    def _raising_factory():
        raise RuntimeError("boom")

    try:
        fetch_with_browser(
            "https://jiji.ng/seeking-work-cvs?query=x",
            data_dir=str(tmp_path),
            dotenv_path=dotenv,
            _playwright_factory=_raising_factory,
        )
    except JijiScrapeError as exc:
        assert "proxypass-TEST" not in str(exc)
        assert "proxyuser" not in str(exc)
    else:
        raise AssertionError("expected JijiScrapeError")
