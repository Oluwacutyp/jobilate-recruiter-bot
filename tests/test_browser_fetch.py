"""Turnstile fallback tests — mocked, never hits real Jiji, never launches a real browser."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.browser_fetch import (
    TURNSTILE_SELECTORS,
    default_profile_dir,
    playwright_enabled,
    playwright_headless,
)
from jobilate.scraper import JijiScraper, JijiScrapeError


def test_fallback_when_requests_returns_challenge():
    calls = {"browser": 0}

    def fake_requests(url):
        raise JijiScrapeError("Jiji returned a challenge/block page (HTTP 403).")

    def fake_browser(url):
        calls["browser"] += 1
        return "<html><body><a href='https://jiji.ng/cv-1'>A CV</a></body></html>"

    s = JijiScraper(min_delay=0, _fetcher=fake_requests, browser_fetcher=fake_browser)
    body = s.fetch("https://jiji.ng/seeking-work-cvs?query=x")
    assert "jiji.ng" in body
    assert calls["browser"] == 1


def test_browser_not_called_when_requests_succeeds():
    calls = {"browser": 0}

    def fake_requests(url):
        return "<html><body>ok, no challenge here</body></html>"

    def fake_browser(url):
        calls["browser"] += 1
        return "<html></html>"

    s = JijiScraper(min_delay=0, _fetcher=fake_requests, browser_fetcher=fake_browser)
    body = s.fetch("https://jiji.ng/seeking-work-cvs?query=y")
    assert "ok" in body
    assert calls["browser"] == 0


def test_browser_not_called_when_fallback_disabled():
    def fake_requests(url):
        raise JijiScrapeError("Jiji returned a challenge/block page (HTTP 403).")

    def fake_browser(url):
        raise AssertionError("browser fallback must not run when disabled")

    s = JijiScraper(
        min_delay=0, _fetcher=fake_requests, browser_fetcher=fake_browser,
        playwright_enabled=False,
    )
    try:
        s.fetch("https://jiji.ng/seeking-work-cvs?query=z")
    except JijiScrapeError as exc:
        assert "challenge" in str(exc).lower()
    else:
        raise AssertionError("expected JijiScrapeError")


def test_turnstile_selectors_cover_expected_patterns():
    joined = " ".join(TURNSTILE_SELECTORS)
    assert "turnstile" in joined
    assert "checkbox" in joined
    assert "sitekey" in joined


def test_persistent_profile_dir_default():
    assert default_profile_dir("./data").endswith("browser_profile")
    os.environ["BROWSER_PROFILE_DIR"] = "/tmp/custom-profile"
    try:
        assert default_profile_dir("./data") == "/tmp/custom-profile"
    finally:
        del os.environ["BROWSER_PROFILE_DIR"]


def test_playwright_env_flags():
    os.environ["PLAYWRIGHT_ENABLED"] = "0"
    try:
        assert playwright_enabled() is False
    finally:
        del os.environ["PLAYWRIGHT_ENABLED"]
    os.environ["PLAYWRIGHT_HEADLESS"] = "1"
    try:
        assert playwright_headless() is True
    finally:
        del os.environ["PLAYWRIGHT_HEADLESS"]
