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
  CF_CLEARANCE (see README) — never logged, never in errors;
- uses an EPHEMERAL browser context by default (launch + new_context,
  no persistent profile dir, so no SingletonLock "profile already in
  use" errors from zombie instances). The old persistent profile is
  only used when BROWSER_PERSISTENT_PROFILE=1 is set explicitly, and
  then stale lock files are cleaned first;
- if desktop Edge still gets "Just a moment...", tries a mobile
  emulation pass (Pixel 7 UA / viewport / touch) with the cookie and
  then without it — Cloudflare treats mobile traffic differently, so
  mobile sometimes passes where desktop fails. Max 4 attempts total
  per URL, with pacing; first success wins.

On any Playwright failure this raises JijiScrapeError — never fakes
results, never returns challenge HTML as if it were a listing.
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time

log = logging.getLogger(__name__)

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

# Mobile emulation (Pixel 7) for the mobile fallback pass. Same jiji.ng
# URL, mobile UA/viewport/touch — Cloudflare treats mobile traffic
# differently, so mobile sometimes passes where desktop fails.
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
MOBILE_VIEWPORT: dict = {"width": 412, "height": 915}
DESKTOP_VIEWPORT: dict = {"width": 1920, "height": 1080}

# Filenames Playwright/Chromium leaves in a persistent profile dir that
# lock it to one process ("profile is already in use"). Cleaned
# best-effort only on the explicit persistent-profile path — never
# deletes user data, only the lock files.
_PROFILE_LOCK_FILES: tuple[str, ...] = (
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "SingletonSync",
)


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


def read_cf_bm(dotenv_path: str | None = None) -> str:
    """Optional __cf_bm cookie, re-read from .env file each scrape.

    __cf_bm is Cloudflare's bot-manager cookie (same Edge Settings
    page as cf_clearance, name "__cf_bm"). Sent alongside cf_clearance
    when present — it helps Cloudflare trust the session. Optional:
    cf_clearance alone is the required one. NEVER logged, never in
    errors. Set in .env as CF_BM=<value>.
    """
    from_file = _read_dotenv_value("CF_BM", dotenv_path)
    if from_file:
        return from_file
    return os.environ.get("CF_BM", "").strip()


def cf_bm_value(dotenv_path: str | None = None) -> str:
    """Back-compat alias for read_cf_bm(). Never logged, never in errors."""
    return read_cf_bm(dotenv_path)


# ---------------------------------------------------------------------------
# Residential proxy (PROXY_URL) — ADDITIVE (2026-10-17).
#
# User-verified: fresh CF_CLEARANCE + mobile fallback STILL blocked
# (2026-10-15/16). Root cause is IP reputation: the AWS datacenter IP
# is flagged by Cloudflare, and a mobile UA from a datacenter IP is
# still a datacenter IP. The durable fix is a residential IP — a
# self-hosted home proxy or a paid residential provider — so the
# bot's traffic comes from a real home IP instead of AWS.
#
# PROXY_URL is re-read from the .env FILE on every scrape (same as
# CF_CLEARANCE — no restart needed). PROXY_URL wins over the
# HTTP_PROXY / HTTPS_PROXY aliases. When unset, behaviour is EXACTLY
# as before (direct, no proxy). The proxy URL (which may contain a
# username/password) is NEVER logged, NEVER in errors, NEVER in
# /config — only the host + scheme are ever shown.
# ---------------------------------------------------------------------------
_PROXY_KEYS: tuple[str, ...] = ("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY")


def _normalize_proxy_url(raw: str) -> str:
    """Strip + add an http:// scheme when the user omitted one.

    "user:pass@host:port" -> "http://user:pass@host:port".
    Returns "" for an empty value. The result may contain
    credentials — callers must NEVER log it.
    """
    url = (raw or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    return url


def read_proxy_url(dotenv_path: str | None = None) -> str:
    """Proxy URL, re-read from .env file each scrape (no restart needed).

    Precedence: PROXY_URL (.env file, then os.environ) wins over
    HTTP_PROXY, which wins over HTTPS_PROXY. Returns the normalised
    URL (with credentials, if any) or "" when no proxy is set.
    NEVER log the return value.
    """
    for key in _PROXY_KEYS:
        from_file = _read_dotenv_value(key, dotenv_path)
        if from_file:
            return _normalize_proxy_url(from_file)
        env_val = os.environ.get(key, "").strip()
        if env_val:
            return _normalize_proxy_url(env_val)
    return ""


def proxy_status(dotenv_path: str | None = None) -> dict:
    """Proxy diagnostics WITHOUT credentials (safe for /config + logs).

    Returns {"set": bool, "host": str, "scheme": str, "source": str}.
    "host" is the hostname only (no user/pass/port). "source" is
    ".env file" / "environment" / "". The proxy URL itself is never
    returned, logged, or put in errors.
    """
    from urllib.parse import urlparse

    for key in _PROXY_KEYS:
        from_file = _read_dotenv_value(key, dotenv_path)
        if from_file:
            parsed = urlparse(_normalize_proxy_url(from_file))
            return {"set": True, "host": parsed.hostname or "",
                    "scheme": parsed.scheme or "",
                    "source": ".env file"}
        env_val = os.environ.get(key, "").strip()
        if env_val:
            parsed = urlparse(_normalize_proxy_url(env_val))
            return {"set": True, "host": parsed.hostname or "",
                    "scheme": parsed.scheme or "",
                    "source": "environment"}
    return {"set": False, "host": "", "scheme": "", "source": ""}


def proxy_config_line(dotenv_path: str | None = None) -> str:
    """One /config line for the proxy — host only, never credentials."""
    st = proxy_status(dotenv_path)
    if st["set"]:
        host = st["host"] or "unknown host"
        return f"PROXY: set (host {host}, from {st['source']})"
    return "PROXY: NOT SET (direct connection; set PROXY_URL in .env for a residential proxy)"


def requests_proxies(dotenv_path: str | None = None) -> dict | None:
    """proxies dict for requests.get/post, or None (direct, unchanged).

    {"http": url, "https": url} when PROXY_URL (or alias) is set.
    The URLs may contain credentials — NEVER log this dict.
    """
    url = read_proxy_url(dotenv_path)
    if not url:
        return None
    return {"http": url, "https": url}


def _playwright_proxy(dotenv_path: str | None = None) -> dict | None:
    """proxy dict for Playwright launch, or None (direct, unchanged).

    {"server": url} — Playwright supports http/https/socks5, with
    auth in the URL. The URL may contain credentials — NEVER log it.
    """
    url = read_proxy_url(dotenv_path)
    if not url:
        return None
    return {"server": url}


def _proxy_log_label(dotenv_path: str | None = None) -> str:
    """Safe log label for proxy failures: 'host <host> (<scheme>)'."""
    st = proxy_status(dotenv_path)
    if not st["set"]:
        return "proxy"
    return f"proxy (host {st['host'] or 'unknown host'}, scheme {st['scheme'] or 'http'})"


def _cloudflare_cookies(dotenv_path: str | None = None, with_cookie: bool = True) -> list[dict]:
    """Cloudflare cookies to inject into a browser context (values never logged).

    Returns [] when with_cookie is False or no cookie is saved. Otherwise
    cf_clearance (+ __cf_bm when CF_BM is set) for .jiji.ng, plus
    cf_clearance for .cloudflareinsights.com (as before).
    """
    if not with_cookie:
        return []
    cookies: list[dict] = []
    clearance = read_cf_clearance(dotenv_path)
    bm = read_cf_bm(dotenv_path)
    if clearance:
        cookies.append({"name": "cf_clearance", "value": clearance,
                        "domain": ".jiji.ng", "path": "/"})
        cookies.append({"name": "cf_clearance", "value": clearance,
                        "domain": ".cloudflareinsights.com", "path": "/"})
    if bm:
        cookies.append({"name": "__cf_bm", "value": bm,
                        "domain": ".jiji.ng", "path": "/"})
    return cookies


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


def _cloudflare_error(url: str, title: str = "", anchors: int = -1, html_len: int = -1,
                       channels_tried: list[str] | None = None,
                       attempts_tried: list[str] | None = None) -> Exception:
    """Build the Cloudflare-block error (never includes HTML or cookies).

    channels_tried / attempts_tried are recorded so the error says
    WHAT was actually tried (e.g. "channels tried: msedge, chromium;
    attempts: desktop+cookie, mobile") — never silently claiming Edge
    was used when Chromium was the one that ran.
    """
    from .scraper import JijiScrapeError

    suffix = ""
    if channels_tried:
        suffix += f" channels tried: {', '.join(channels_tried)}."
    if attempts_tried:
        suffix += f" attempts: {', '.join(attempts_tried)}."
    return JijiScrapeError(
        "Cloudflare 'Just a moment...' challenge — bot's browser was flagged "
        "as automated. Try real Edge profile / CF_CLEARANCE, or wait and retry. "
        f"for {_truncate_url(url)} diag: title={str(title)[:120]!r} anchors={anchors} html_len={html_len}"
        + suffix
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


def use_persistent_profile() -> bool:
    """True only when BROWSER_PERSISTENT_PROFILE=1 is set explicitly.

    Default is the EPHEMERAL context (no profile dir, no lock file).
    The persistent profile is a legacy opt-in — it is the only path
    that can hit "profile is already in use" from a zombie instance.
    """
    return os.environ.get("BROWSER_PERSISTENT_PROFILE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _clean_stale_profile_locks(profile: str) -> None:
    """Delete stale Singleton* lock files in a persistent profile dir.

    Best-effort only, and only on the explicit persistent-profile path.
    Deletes lock files, never user data (no cookies/history/cache).
    If a live Edge/Playwright instance still holds the profile, its
    lock is recreated on next launch — cleaning a live lock is
    harmless: the next launch either re-locks or reports "already
    in use" again, which the channel fallback then handles.
    """
    for name in _PROFILE_LOCK_FILES:
        try:
            path = os.path.join(profile, name)
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            continue


def _launch_persistent_context(p, profile: str, dotenv_path: str | None = None):
    """Launch persistent context: Edge -> Chrome -> Chromium.

    LEGACY opt-in only (BROWSER_PERSISTENT_PROFILE=1). Stale lock
    files are cleaned first so a zombie previous scrape cannot leave
    a permanent "profile is already in use" error.
    Returns (ctx, channel_used). channel_used is "msedge" / "chrome" /
    "chromium" (default) — recorded for the log line, never the cookie.
    Raises the last error if all channels fail.
    """
    os.makedirs(profile, exist_ok=True)
    _clean_stale_profile_locks(profile)
    # Proxy passes: with proxy first (when set), then ONE direct pass.
    # The proxy URL is never logged — only the safe host/scheme label.
    proxy = _playwright_proxy(dotenv_path)
    passes: list[dict | None] = [proxy, None] if proxy else [None]
    last_exc: Exception | None = None
    for pass_idx, proxy_opt in enumerate(passes):
        if pass_idx == 1:
            log.info("proxy failed, falling back to direct (%s)", _proxy_log_label(dotenv_path))
        for channel in BROWSER_CHANNELS:
            kwargs: dict = dict(
                user_data_dir=profile,
                headless=playwright_headless(),
                viewport=dict(DESKTOP_VIEWPORT),
                locale="en-NG",
                user_agent=jiji_user_agent(dotenv_path),
                args=["--disable-blink-features=AutomationControlled"],
            )
            if proxy_opt is not None:
                kwargs["proxy"] = proxy_opt
            if channel is not None:
                kwargs["channel"] = channel
            try:
                ctx = p.chromium.launch_persistent_context(**kwargs)
                log.debug("browser launch: persistent context, channel=%s", channel or "chromium")
                return ctx, channel or "chromium"
            except Exception as exc:  # noqa: BLE001 - try next channel
                log.debug("browser launch failed for channel=%s: %s", channel or "chromium", str(exc)[:200])
                last_exc = exc
                continue
    raise last_exc if last_exc is not None else RuntimeError("Playwright launch failed")


def _launch_ephemeral_browser(p, dotenv_path: str | None = None):
    """Launch an EPHEMERAL browser (no profile dir, no lock file).

    Tries channels msedge -> chrome -> Chromium. Returns
    (browser, channel_used, channels_tried). channels_tried records
    every channel actually attempted (for error messages — never
    claim Edge ran when Chromium was the one that launched).
    Raises the last launch error if all channels fail.
    """
    channels_tried: list[str] = []
    last_exc: Exception | None = None
    # Proxy passes: with proxy first (when set), then ONE direct pass.
    # The proxy URL is never logged — only the safe host/scheme label.
    proxy = _playwright_proxy(dotenv_path)
    passes: list[dict | None] = [proxy, None] if proxy else [None]
    for pass_idx, proxy_opt in enumerate(passes):
        if pass_idx == 1:
            log.info("proxy failed, falling back to direct (%s)", _proxy_log_label(dotenv_path))
        for channel in BROWSER_CHANNELS:
            channels_tried.append(channel or "chromium")
            kwargs: dict = dict(
                headless=playwright_headless(),
                args=["--disable-blink-features=AutomationControlled"],
            )
            if proxy_opt is not None:
                kwargs["proxy"] = proxy_opt
            if channel is not None:
                kwargs["channel"] = channel
            try:
                browser = p.chromium.launch(**kwargs)
                log.debug("browser launch: ephemeral, channel=%s", channel or "chromium")
                return browser, channel or "chromium", channels_tried
            except Exception as exc:  # noqa: BLE001 - try next channel
                log.debug("browser launch failed for channel=%s: %s", channel or "chromium", str(exc)[:200])
                last_exc = exc
                continue
    raise last_exc if last_exc is not None else RuntimeError("Playwright launch failed")


def _new_ephemeral_context(browser, *, mobile: bool, with_cookie: bool,
                           dotenv_path: str | None = None):
    """Ephemeral context for one attempt (desktop or mobile).

    Desktop: Edge UA + 1920x1080. Mobile: Pixel 7 UA + 412x915 +
    has_touch + is_mobile. Stealth init script + Cloudflare cookies
    (when with_cookie) are applied. Returns the context.
    """
    if mobile:
        ctx = browser.new_context(
            viewport=dict(MOBILE_VIEWPORT),
            locale="en-NG",
            user_agent=MOBILE_USER_AGENT,
            has_touch=True,
            is_mobile=True,
        )
    else:
        ctx = browser.new_context(
            viewport=dict(DESKTOP_VIEWPORT),
            locale="en-NG",
            user_agent=jiji_user_agent(dotenv_path),
        )
    try:
        ctx.add_init_script(STEALTH_INIT_SCRIPT)
    except Exception:
        pass
    cookies = _cloudflare_cookies(dotenv_path, with_cookie=with_cookie)
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception:
            pass
    return ctx


def _fetch_with_browser_once(
    url: str,
    *,
    mobile: bool,
    with_cookie: bool,
    timeout_seconds: int,
    dotenv_path: str | None = None,
    profile_dir: str | None = None,
    data_dir: str = "./data",
    _playwright_factory=None,
) -> tuple[str, list[str]]:
    """ONE browser attempt (desktop/mobile x cookie/no-cookie).

    Returns (html, channels_tried). Raises JijiScrapeError on challenge
    / block / launch failure. Uses the ephemeral context by default;
    the persistent profile only when BROWSER_PERSISTENT_PROFILE=1.
    """
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

    channels_tried: list[str] = []
    with _playwright_factory() as p:
        browser = None
        ctx = None
        try:
            if use_persistent_profile():
                profile = profile_dir or default_profile_dir(data_dir)
                ctx, channel_used = _launch_persistent_context(p, profile, dotenv_path)
                channels_tried.append(channel_used)
                # Stealth + cookies on the persistent context (as before).
                try:
                    ctx.add_init_script(STEALTH_INIT_SCRIPT)
                except Exception:
                    pass
                cookies = _cloudflare_cookies(dotenv_path, with_cookie=with_cookie)
                if cookies:
                    try:
                        ctx.add_cookies(cookies)
                    except Exception:
                        pass
            else:
                browser, channel_used, channels_tried = _launch_ephemeral_browser(p, dotenv_path)
                ctx = _new_ephemeral_context(
                    browser, mobile=mobile, with_cookie=with_cookie, dotenv_path=dotenv_path,
                )
                log.debug(
                    "browser attempt: mobile=%s with_cookie=%s channel=%s",
                    mobile, with_cookie, channel_used,
                )
            page = ctx.new_page()
            page.goto(url, timeout=timeout_seconds * 1000, wait_until="domcontentloaded")
            _human_like_pause(page)
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
                    channels_tried=channels_tried,
                )
            if _page_looks_blocked(html):
                raise JijiScrapeError(
                    "Turnstile challenge did not clear "
                    f"within {timeout_seconds}s for {_truncate_url(url)}. "
                    "Solve in Edge, update CF_CLEARANCE in .env, retry."
                )
            html = _wait_for_cards(page, html)
            if _is_cloudflare_challenge_html(html, _safe_title(page)):
                raise _cloudflare_error(url, title=_safe_title(page), html_len=len(html),
                                        channels_tried=channels_tried)
            if _page_looks_blocked(html):
                raise JijiScrapeError(
                    f"Still blocked after browser fetch for {_truncate_url(url)} "
                    "(Turnstile challenge still present). Solve in Edge, "
                    "update CF_CLEARANCE in .env, retry."
                )
            return html, channels_tried
        except JijiScrapeError as _exc:
            # Surface which channels actually ran, so the outer loop's
            # final error can name them (never claim Edge ran when
            # Chromium was the one that launched).
            _exc._channels_tried = list(channels_tried)  # type: ignore[attr-defined]
            raise
        finally:
            try:
                if ctx is not None:
                    ctx.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass


def fetch_with_browser(
    url: str,
    *,
    profile_dir: str | None = None,
    data_dir: str = "./data",
    timeout_seconds: int = 30,
    dotenv_path: str | None = None,
    _playwright_factory=None,
) -> str:
    """Fetch a URL with REAL Edge (fallback Chrome -> Chromium) + mobile.

    Fallback chain (first-class, documented in README):
      (1) requests + CF_CLEARANCE + Edge UA  [in scraper.fetch]
      (2) Playwright real Edge + stealth + CF_CLEARANCE in context
      (3) Playwright desktop Edge, no cookie (fresh session)
      (4) Playwright mobile emulation (Pixel 7) + CF_CLEARANCE
      (5) Playwright mobile emulation, no cookie
      (6) clear human handoff error ("solve in Edge, update
          CF_CLEARANCE in .env, retry") — never a fake result.

    Max 4 browser attempts per URL, with pacing between attempts;
    first success wins. Each attempt uses an EPHEMERAL context (no
    profile dir, no SingletonLock) unless BROWSER_PERSISTENT_PROFILE=1.
    Returns page HTML. Raises JijiScrapeError (from scraper) on any
    failure. `_playwright_factory` exists for tests to inject a fake.
    The CF_CLEARANCE / CF_BM values are NEVER logged and NEVER in errors.
    """
    from .scraper import JijiScrapeError

    attempts = [
        {"label": "desktop+cookie", "mobile": False, "with_cookie": True},
        {"label": "desktop", "mobile": False, "with_cookie": False},
        {"label": "mobile+cookie", "mobile": True, "with_cookie": True},
        {"label": "mobile", "mobile": True, "with_cookie": False},
    ]
    channels_tried: list[str] = []
    attempt_labels: list[str] = []
    last_exc: Exception | None = None
    for i, attempt in enumerate(attempts):
        attempt_labels.append(attempt["label"])
        try:
            html, tried = _fetch_with_browser_once(
                url,
                mobile=attempt["mobile"],
                with_cookie=attempt["with_cookie"],
                timeout_seconds=timeout_seconds,
                dotenv_path=dotenv_path,
                profile_dir=profile_dir,
                data_dir=data_dir,
                _playwright_factory=_playwright_factory,
            )
            for ch in tried:
                if ch not in channels_tried:
                    channels_tried.append(ch)
            return html
        except JijiScrapeError as exc:
            last_exc = exc
            for ch in getattr(exc, "_channels_tried", []) or []:
                if ch not in channels_tried:
                    channels_tried.append(ch)
            msg = str(exc).lower()
            # Only Cloudflare/turnstile blocks merit the next attempt.
            # Missing Playwright / launch errors on every channel are
            # final — retrying them 4x would just repeat the same error.
            if "cloudflare" not in msg and "just a moment" not in msg \
                    and "turnstile" not in msg and "blocked" not in msg \
                    and "challenge" not in msg:
                raise
            if i < len(attempts) - 1:
                time.sleep(1.0)  # pacing between attempts, never hammering
            continue
        except Exception as exc:  # noqa: BLE001 - factory/launch failure
            # NEVER leak cookies: only the URL + truncated cause.
            raise JijiScrapeError(
                f"Browser fetch failed for {_truncate_url(url)}: {str(exc)[:300]}"
            ) from exc
    # All attempts blocked: report WHAT was tried (channels + attempts).
    raise JijiScrapeError(
        "Browser fetch failed for " + _truncate_url(url) +
        ": still blocked by Cloudflare 'Just a moment...' after "
        + ", ".join(attempt_labels) +
        (f" (channels tried: {', '.join(channels_tried)})" if channels_tried else "") +
        ". Solve in Edge, update CF_CLEARANCE in .env, retry."
    ) from last_exc




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
