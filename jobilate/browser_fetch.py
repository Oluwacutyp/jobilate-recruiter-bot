"""Playwright fallback for Cloudflare Turnstile / "Just a moment...".

ADDITIVE ONLY: the requests path in scraper.py stays the fast/default
path. This module is used ONLY when requests hits a challenge/block
page.

User-verified 2026-10-14: same RDP, same IP — real Edge passes
Cloudflare, bot's Playwright Chromium gets "Just a moment..."
(title='Just a moment...', anchors=2). That PROVES it is NOT IP
blocking alone — it is automation fingerprinting. Edge passes
because it is real Edge + human signals. Playwright's bundled
Chromium fails because it is detected (navigator.webdriver, CDP
flags, missing human signals, fresh profile).

So this fallback now (ADDITIVE — requests path unchanged):
- launches REAL Microsoft Edge (channel="msedge"), falling back to
  Chrome -> Playwright's Chromium only if Edge is not installed;
- applies a standard stealth init script (hides navigator.webdriver,
  spoofs window.chrome / plugins / languages / permissions — no
  solving services, no token forgery, no CDP evasion tricks);
- does small human-like behaviour (pause, mouse move, slow scroll);
- polls up to 30s for a "Just a moment..." / "Checking your browser"
  challenge to clear (it is an automatic JS check, NOT a checkbox
  click — there is nothing to click on that page);
- optionally reuses a human-verified cf_clearance cookie from
  CF_CLEARANCE (see README) — never logged, never in errors.

On any Playwright failure this raises JijiScrapeError — never fakes
results, never returns challenge HTML as if it were a listing.
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

# Default UA is Microsoft Edge on Windows (Edg/...) — the user passed
# Cloudflare in Edge on the RDP, NOT Chrome. If CF_CLEARANCE is set,
# the cookie was solved in Edge, so the bot MUST use the same Edge UA
# (same browser + same RDP + same UA) or Cloudflare may reject it.
# Override with JIJI_USER_AGENT in .env (re-read each scrape).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)

# Playwright channel fallback order: Edge (preinstalled on Windows RDP,
# the browser the user solved in) -> Chrome -> bundled Chromium.
BROWSER_CHANNELS: tuple[str | None, ...] = ("msedge", "chrome", None)


def _dotenv_candidates(dotenv_path: str | None = None) -> list[str]:
    """Candidate .env paths: explicit arg, DOTENV_PATH, ./​.env, repo-root .env."""
    paths: list[str] = []
    if dotenv_path:
        paths.append(dotenv_path)
    env_path = os.environ.get("DOTENV_PATH", "").strip()
    if env_path:
        paths.append(env_path)
    paths.append(os.path.join(os.getcwd(), ".env"))
    # Repo root = parent of this package dir (…/jobilate-recruiter-bot/.env).
    try:
        paths.append(os.path.join(os.path.dirname(__file__), "..", ".env"))
    except Exception:
        pass
    return paths


def _read_dotenv_value(key: str, dotenv_path: str | None = None) -> str:
    """Read one KEY from the .env FILE (fresh on every call).

    The user updates .env on the RDP without restarting the bot, so
    this is re-read on EVERY scrape — never cached. Strips quotes.
    Returns '' when missing. NEVER logs the value.
    """
    for path in _dotenv_candidates(dotenv_path):
        try:
            if not path or not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        v = v.strip()
                        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                            v = v[1:-1]
                        return v.strip()
        except Exception:
            continue
    return ""


def read_cf_clearance(dotenv_path: str | None = None) -> str:
    """Human-verified cf_clearance, re-read from .env file each scrape.

    .env file wins (fresh, no restart needed); os.environ is the
    fallback (e.g. Termux / CI where there is no .env file).
    NEVER log the value, never put it in errors.
    """
    from_file = _read_dotenv_value("CF_CLEARANCE", dotenv_path)
    if from_file:
        return from_file
    return os.environ.get("CF_CLEARANCE", "").strip()


def jiji_user_agent(dotenv_path: str | None = None) -> str:
    """UA for BOTH requests and Playwright (same UA, or cookie rejected).

    JIJI_USER_AGENT in .env (re-read each scrape) wins; os.environ next;
    default is the Edge UA (the browser the cookie was solved in).
    """
    from_file = _read_dotenv_value("JIJI_USER_AGENT", dotenv_path)
    if from_file:
        return from_file
    return os.environ.get("JIJI_USER_AGENT", "").strip() or DEFAULT_USER_AGENT


def dotenv_path_checked(dotenv_path: str | None = None) -> str:
    """First existing .env candidate, else the repo-root .env path.

    Used by /config so the user can verify WHICH .env the bot reads.
    Note: only the exact filename ".env" is ever read — ".env.txt"
    (what Notepad saves when "Save as type" is Text) is ignored.
    """
    candidates = _dotenv_candidates(dotenv_path)
    for path in candidates:
        try:
            if path and os.path.isfile(path):
                return os.path.abspath(path)
        except Exception:
            continue
    return os.path.abspath(candidates[-1]) if candidates else ""


def cf_clearance_status(dotenv_path: str | None = None) -> dict:
    """CF_CLEARANCE diagnostics WITHOUT the value (never log it).

    Returns {"set": bool, "length": int, "source": str, "env_path": str}.
    "source" is ".env file" / "environment" / "". The cookie value
    itself is never returned, logged, or put in errors.
    """
    from_file = _read_dotenv_value("CF_CLEARANCE", dotenv_path)
    if from_file:
        return {"set": True, "length": len(from_file),
                "source": ".env file",
                "env_path": dotenv_path_checked(dotenv_path)}
    env_val = os.environ.get("CF_CLEARANCE", "").strip()
    if env_val:
        return {"set": True, "length": len(env_val),
                "source": "environment",
                "env_path": dotenv_path_checked(dotenv_path)}
    return {"set": False, "length": 0, "source": "",
            "env_path": dotenv_path_checked(dotenv_path)}

# Standard stealth init script: hide automation flags + restore the
# signals a real Edge has. No solving services, no token forgery,
# no CDP evasion tricks — only hiding the automation markers that
# Cloudflare uses to flag Playwright's bundled Chromium.
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en', 'en-NG'],
});
if (window.navigator.permissions && window.navigator.permissions.query) {
  const _origQuery = window.navigator.permissions.query;
  window.navigator.permissions.query = (parameters) => (
    parameters && parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _origQuery(parameters)
  );
}
if (navigator.hardwareConcurrency === undefined) {
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
}
if (navigator.deviceMemory === undefined) {
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
}
"""

# Cloudflare automatic JS challenge ("Just a moment..." interstitial).
# This is NOT the Turnstile checkbox — there is nothing to click on
# this page; the browser must pass the automatic check (real Edge +
# human signals + time) for the title to change to the real listing.
CLOUDFLARE_CHALLENGE_TITLES: tuple[str, ...] = (
    "just a moment",
    "checking your browser",
    "attention required",
    "cf-challenge",
)

CLOUDFLARE_CHALLENGE_PHRASES: tuple[str, ...] = (
    "just a moment",
    "checking your browser",
    "attention required",
)


def cf_clearance_value(dotenv_path: str | None = None) -> str:
    """Human-verified cf_clearance cookie, re-read from .env each scrape.

    Back-compat alias for read_cf_clearance(). The value itself is
    NEVER logged and NEVER put in error messages.
    """
    return read_cf_clearance(dotenv_path)


def _is_cloudflare_challenge_html(html: str, title: str = "") -> bool:
    """True for Cloudflare's automatic 'Just a moment...' challenge page."""
    t = (title or "").lower()
    if any(phrase in t for phrase in CLOUDFLARE_CHALLENGE_TITLES):
        return True
    low = (html or "").lower()
    # Title in the HTML itself (page.title() may be unavailable on fakes).
    if "<title>" in low:
        try:
            title_html = low.split("<title>", 1)[1].split("</title>", 1)[0]
        except Exception:
            title_html = ""
        if any(phrase in title_html for phrase in CLOUDFLARE_CHALLENGE_TITLES):
            return True
    # Body says "Just a moment..." AND mentions Cloudflare.
    if "just a moment" in low and "cloudflare" in low:
        return True
    if "checking your browser" in low and "cloudflare" in low:
        return True
    return False


def _cloudflare_error(url: str, title: str = "", anchors: int = -1, html_len: int = -1) -> Exception:
    """Build the Cloudflare-block error (never includes HTML or cookies)."""
    from .scraper import JijiScrapeError

    return JijiScrapeError(
        "Cloudflare 'Just a moment...' challenge — bot's browser was flagged "
        "as automated. Try real Edge profile / CF_CLEARANCE, or wait and retry. "
        f"for {_truncate_url(url)} diag: title={str(title)[:120]!r} anchors={anchors} html_len={html_len}"
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


def _safe_title(page) -> str:
    """page.title() or '' — fakes may not implement title()."""
    try:
        return str(page.title() or "")
    except Exception:
        return ""


def _human_like_pause(page) -> None:
    """Small human-like behaviour: pause, mouse move, slow scroll.

    Best-effort — any failure (e.g. fakes without mouse) is ignored.
    """
    try:
        time.sleep(random.uniform(0.5, 1.5))
    except Exception:
        pass
    try:
        page.mouse.move(960, 540)
        time.sleep(random.uniform(0.2, 0.6))
        page.mouse.wheel(0, 500)
    except Exception:
        pass


def _try_turnstile_click(page, timeout_seconds: int) -> bool:
    """Try to click the Turnstile checkbox once. Returns True if clicked."""
    for selector in TURNSTILE_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.count() == 0:
                continue
            try:
                box = loc.bounding_box()
            except Exception:
                box = None
            if box is not None:
                try:
                    page.mouse.move(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                    time.sleep(random.uniform(0.2, 0.6))
                except Exception:
                    pass
            loc.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


# Selector for Jiji CV result cards (verified against live HTML 2026-10-14).
CARD_SELECTOR = "a.qa-advert-list-item, a[href*='-cvs/']"


def _wait_for_cards(page, html: str, timeout_ms: int = 10000) -> str:
    """Wait for JS-rendered CV cards before returning HTML (ADDITIVE).

    Jiji is a Nuxt app: ``domcontentloaded`` HTML can precede the
    rendered cards. If the page already says "0 results" / "No results"
    it legitimately has no cards — return immediately, don't burn the
    timeout. On wait timeout (or a fake page without wait_for_selector
    in tests) return the current HTML; the parser decides (0-results
    -> [], no cards -> diagnostic error). Never raises.
    """
    try:
        low = (html or "").lower()
        if "0 results" in low or "no results" in low:
            return html
        page.wait_for_selector(CARD_SELECTOR, timeout=timeout_ms)
        return page.content()
    except Exception:  # noqa: BLE001 - wait failure must not kill the fetch
        return html


def _truncate_url(url: str, limit: int = 120) -> str:
    """Truncate a URL for error messages (local copy — avoids a top-level
    circular import with scraper; scraper.truncate_url is identical)."""
    url = url or ""
    if len(url) <= limit:
        return url
    return url[:limit] + "..."


def _launch_persistent_context(p, profile: str, dotenv_path: str | None = None):
    """Launch persistent context: Edge -> Chrome -> Chromium.

    Returns (ctx, channel_used). channel_used is "msedge" / "chrome" /
    "chromium" (default) — recorded for the log line, never the cookie.
    Raises the last error if all channels fail.
    """
    last_exc: Exception | None = None
    for channel in BROWSER_CHANNELS:
        kwargs: dict = dict(
            user_data_dir=profile,
            headless=playwright_headless(),
            viewport={"width": 1920, "height": 1080},
            locale="en-NG",
            user_agent=jiji_user_agent(dotenv_path),
            args=["--disable-blink-features=AutomationControlled"],
        )
        if channel is not None:
            kwargs["channel"] = channel
        try:
            ctx = p.chromium.launch_persistent_context(**kwargs)
            return ctx, channel or "chromium"
        except Exception as exc:  # noqa: BLE001 - try next channel
            last_exc = exc
            continue
    raise last_exc if last_exc is not None else RuntimeError("Playwright launch failed")


def fetch_with_browser(
    url: str,
    *,
    profile_dir: str | None = None,
    data_dir: str = "./data",
    timeout_seconds: int = 30,
    dotenv_path: str | None = None,
    _playwright_factory=None,
) -> str:
    """Fetch a URL with REAL Edge (fallback Chrome -> Chromium).

    Fallback chain (first-class, documented in README):
      (1) requests + CF_CLEARANCE + Edge UA  [in scraper.fetch]
      (2) Playwright real Edge + stealth + CF_CLEARANCE in context
      (3) clear human handoff error ("solve in Edge, update
          CF_CLEARANCE in .env, retry") — never a fake result.

    Returns page HTML. Raises JijiScrapeError (from scraper) on any
    failure. `_playwright_factory` exists for tests to inject a fake.
    The CF_CLEARANCE value is NEVER logged and NEVER in errors.
    """
    # Local import so the module imports cleanly without Playwright.
    from .scraper import JijiScrapeError

    if _playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise JijiScrapeError(
                "Playwright is not installed — cannot use browser fallback. "
                "Run: pip install -r requirements.txt && playwright install msedge"
            ) from exc
        _playwright_factory = sync_playwright

    profile = profile_dir or default_profile_dir(data_dir)
    os.makedirs(profile, exist_ok=True)
    try:
        with _playwright_factory() as p:
            ctx, channel_used = _launch_persistent_context(p, profile, dotenv_path)
            try:
                # Stealth init script (best-effort; fakes may lack it).
                try:
                    ctx.add_init_script(STEALTH_INIT_SCRIPT)
                except Exception:
                    pass
                # FIRST-CLASS fallback: human-verified cf_clearance cookie
                # in the browser context (re-read from .env each scrape,
                # so updating .env needs NO restart). Never logged.
                clearance = read_cf_clearance(dotenv_path)
                if clearance:
                    try:
                        ctx.add_cookies([
                            {"name": "cf_clearance", "value": clearance,
                             "domain": ".jiji.ng", "path": "/"},
                            {"name": "cf_clearance", "value": clearance,
                             "domain": ".cloudflareinsights.com", "path": "/"},
                        ])
                    except Exception:
                        pass
                page = ctx.new_page()
                page.goto(url, timeout=timeout_seconds * 1000, wait_until="domcontentloaded")
                _human_like_pause(page)
                # Poll for challenges to clear (up to timeout_seconds).
                # Two challenge types:
                #  - Turnstile checkbox ("Verify you are human"): click once.
                #  - "Just a moment..." automatic JS check: NOTHING to
                #    click — wait for the title to become the real
                #    listing (real Edge + human signals + time).
                clicked = False
                deadline = time.monotonic() + timeout_seconds
                html = ""
                title = ""
                while True:
                    html = page.content()
                    title = _safe_title(page)
                    if _page_looks_blocked(html) and not clicked:
                        clicked = _try_turnstile_click(page, timeout_seconds)
                        if clicked:
                            continue  # re-read after the click
                    if not _is_cloudflare_challenge_html(html, title) and not _page_looks_blocked(html):
                        break
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(1.0)
                if _is_cloudflare_challenge_html(html, title):
                    try:
                        anchor_count = len(page.content().split("<a")) - 1
                    except Exception:
                        anchor_count = -1
                    raise _cloudflare_error(
                        url, title=title,
                        anchors=anchor_count, html_len=len(html),
                    )
                if _page_looks_blocked(html):
                    raise JijiScrapeError(
                        "Turnstile challenge did not clear "
                        f"within {timeout_seconds}s for {_truncate_url(url)}. "
                        "Solve in Edge, update CF_CLEARANCE in .env, retry."
                    )
                # Cards may render via JS after domcontentloaded — wait.
                html = _wait_for_cards(page, html)
                if _is_cloudflare_challenge_html(html, _safe_title(page)):
                    raise _cloudflare_error(url, title=_safe_title(page), html_len=len(html))
                if _page_looks_blocked(html):
                    raise JijiScrapeError(
                        f"Still blocked after browser fetch for {_truncate_url(url)} "
                        "(Turnstile challenge still present). Solve in Edge, "
                        "update CF_CLEARANCE in .env, retry."
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
        # NEVER leak the cookie: the message contains only the URL + cause.
        cause = str(exc)[:300]
        raise JijiScrapeError(
            f"Browser fetch failed for {_truncate_url(url)}: {cause}"
        ) from exc


async def fetch_with_browser_async(
    url: str,
    *,
    profile_dir: str | None = None,
    data_dir: str = "./data",
    timeout_seconds: int = 30,
    dotenv_path: str | None = None,
    _playwright_factory=None,
) -> str:
    """Async-safe browser fetch for Telegram handlers (async context).

    The Playwright Sync API raises "Sync API inside the asyncio loop"
    when called on the event-loop thread. Running the sync fetch in
    ``asyncio.to_thread`` puts it on a worker thread with no running
    loop, so the Sync API works. Sync callers keep using
    ``fetch_with_browser``.
    """
    import asyncio

    return await asyncio.to_thread(
        fetch_with_browser,
        url,
        profile_dir=profile_dir,
        data_dir=data_dir,
        timeout_seconds=timeout_seconds,
        dotenv_path=dotenv_path,
        _playwright_factory=_playwright_factory,
    )
