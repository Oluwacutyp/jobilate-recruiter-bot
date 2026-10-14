"""Playwright fallback for Cloudflare Turnstile "Verify you're human".

ADDITIVE ONLY: the requests path in scraper.py stays the fast/default
path. This module is used ONLY when requests hits a challenge/block
page. It launches a real Chromium, clicks the Turnstile checkbox
(a real browser click — no solving services, no token forgery, no
headless-evasion tricks), and returns the resulting HTML so the
existing parsers work unchanged.

Why a separate browser is needed: solving the challenge in Chrome
sets cookies in Chrome only. The bot's requests session has separate
cookies/fingerprint, so it still sees the challenge. The bot's own
persistent browser profile (DATA_DIR/browser_profile) holds the
verified session across runs — first run may need to verify, later
runs reuse it.

On any Playwright failure (not installed, launch fails, timeout,
still blocked) this raises JijiScrapeError — never fakes results.
"""
from __future__ import annotations

import os
import random
import sys
import time

# Selectors tried in order to find the Turnstile checkbox.
TURNSTILE_SELECTORS: list[str] = [
    'iframe[src*="turnstile"]',
    '[data-sitekey]',
    'input[type="checkbox"]',
]

TURNSTILE_PHRASES: tuple[str, ...] = (
    "verify you are human",
    "verify you're human",
    "challenge",
    "cloudflare",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def default_profile_dir(data_dir: str = "./data") -> str:
    """Persistent browser profile dir (holds the verified session)."""
    env = os.environ.get("BROWSER_PROFILE_DIR", "").strip()
    if env:
        return env
    return os.path.join(data_dir, "browser_profile")


def playwright_enabled() -> bool:
    """True unless PLAYWRIGHT_ENABLED=0. Missing Playwright -> False at use time."""
    return os.environ.get("PLAYWRIGHT_ENABLED", "1").strip() not in ("0", "false", "no", "off")


def playwright_headless() -> bool:
    """Headless default: headed (False) on Windows (has a display, best
    Turnstile pass rate); headless (True) elsewhere. Env overrides."""
    raw = os.environ.get("PLAYWRIGHT_HEADLESS", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return sys.platform != "win32"


def _page_looks_blocked(html: str) -> bool:
    low = (html or "").lower()
    return "verify you are human" in low or "verify you're human" in low


def fetch_with_browser(
    url: str,
    *,
    profile_dir: str | None = None,
    data_dir: str = "./data",
    timeout_seconds: int = 30,
    _playwright_factory=None,
) -> str:
    """Fetch a URL with real Chromium, clicking Turnstile if present.

    Returns page HTML. Raises JijiScrapeError (from scraper) on any
    failure. `_playwright_factory` exists for tests to inject a fake.
    """
    # Local import so the module imports cleanly without Playwright.
    from .scraper import JijiScrapeError

    if _playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise JijiScrapeError(
                "Playwright is not installed — cannot use browser fallback. "
                "Run: pip install -r requirements.txt && playwright install chromium"
            ) from exc
        _playwright_factory = sync_playwright

    profile = profile_dir or default_profile_dir(data_dir)
    os.makedirs(profile, exist_ok=True)
    try:
        with _playwright_factory() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=profile,
                headless=playwright_headless(),
                viewport={"width": 1920, "height": 1080},
                locale="en-NG",
                user_agent=DEFAULT_USER_AGENT,
            )
            try:
                page = ctx.new_page()
                page.goto(url, timeout=timeout_seconds * 1000, wait_until="domcontentloaded")
                # Small human-like pause before looking for the checkbox.
                time.sleep(random.uniform(0.5, 1.5))
                html = page.content()
                if _page_looks_blocked(html):
                    clicked = False
                    for selector in TURNSTILE_SELECTORS:
                        try:
                            loc = page.locator(selector).first
                            if loc.count() == 0:
                                continue
                            # Mouse move toward the checkbox, then click.
                            box = loc.bounding_box()
                            if box is not None:
                                page.mouse.move(
                                    box["x"] + box["width"] / 2,
                                    box["y"] + box["height"] / 2,
                                )
                                time.sleep(random.uniform(0.2, 0.6))
                            loc.click(timeout=5000)
                            clicked = True
                            break
                        except Exception:
                            continue
                    if clicked:
                        # Wait for the challenge to clear (or timeout).
                        deadline = time.monotonic() + timeout_seconds
                        while time.monotonic() < deadline:
                            time.sleep(1.0)
                            html = page.content()
                            if not _page_looks_blocked(html):
                                break
                        else:
                            raise JijiScrapeError(
                                "Turnstile checkbox clicked but challenge did not clear "
                                f"within {timeout_seconds}s for {url}."
                            )
                    else:
                        # No clickable checkbox found — return what we got;
                        # caller checks for challenge text.
                        html = page.content()
                else:
                    html = page.content()
                if _page_looks_blocked(html):
                    raise JijiScrapeError(
                        f"Still blocked after browser fetch for {url} "
                        "(Turnstile challenge still present). Try again later."
                    )
                return html
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
    except JijiScrapeError:
        raise
    except Exception as exc:
        raise JijiScrapeError(f"Browser fetch failed for {url}: {exc}") from exc
