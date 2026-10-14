"""Jiji Seeking Work - CV scraper: public HTML only, NO login, NO API.

Jiji publishes no official API (verified via Devon Jiji connector
findings). This scraper fetches public pages with requests +
BeautifulSoup, enforces >=3s between page loads, caches for 15 min,
and fails fast with JijiScrapeError when the page structure changes or
a challenge page appears — never returning empty results that look
like 'no CVs'. The bot NEVER contacts sellers/candidates on Jiji.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - exercised only without deps
    requests = None  # type: ignore
    BeautifulSoup = None  # type: ignore

JIJI_BASE = "https://jiji.ng"
JIJI_CV_SEARCH = JIJI_BASE + "/seeking-work-cvs?query={query}"
USER_AGENT = "JobilateRecruiterBot/0.1 (+recruiter research; polite crawler)"

FIELD_LABELS = ("Job Type", "Employment Status", "Education", "Highest Qualification", "Skills", "Languages", "Certifications", "Previous Work Experience", "Expected Salary", "Location")


class JijiScrapeError(Exception):
    pass


def _is_challenge_text(text: str) -> bool:
    low = (text or "").lower()
    return ("challenge" in low[:2000] and "cloudflare" in low[:2000]) or (
        "verify you are human" in low or "verify you're human" in low
    )


@dataclass
class JijiScraper:
    min_delay: float = 3.0
    cache_ttl_seconds: int = 900
    _last_fetch: float = field(default=0.0, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)
    _fetcher: Callable[[str], str] | None = field(default=None, repr=False)
    # ADDITIVE (2026-10-14): Playwright Turnstile fallback.
    # browser_fetcher(url) -> HTML. When None, fetch_with_browser is used.
    browser_fetcher: Callable[[str], str] | None = field(default=None, repr=False)
    playwright_enabled: bool = True
    profile_dir: str | None = None
    data_dir: str = "./data"

    # ---- polite fetching ----
    def fetch(self, url: str) -> str:
        now = time.monotonic()
        if url in self._cache:
            ts, body = self._cache[url]
            if now - ts < self.cache_ttl_seconds:
                return body
        wait = self.min_delay - (now - self._last_fetch)
        if wait > 0:
            time.sleep(wait)
        self._last_fetch = time.monotonic()
        try:
            body = self._fetch_requests(url)
            # _fetcher (test/mock) path may return challenge HTML instead of
            # raising — treat it as a challenge too so fallback still works.
            if _is_challenge_text(body):
                raise JijiScrapeError(
                    "Jiji returned a challenge/block page. Trying browser fallback once."
                )
        except JijiScrapeError as exc:
            # Challenge/block only: try the real-browser fallback ONCE.
            # Any other failure (network, structure) raises as before.
            if not self._looks_like_challenge_error(exc):
                raise
            if not self.playwright_enabled:
                raise
            body = self._fetch_browser(url)
        self._cache[url] = (time.monotonic(), body)
        return body

    @staticmethod
    def _looks_like_challenge_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "challenge" in msg or "403" in msg or "503" in msg or "blocked" in msg

    def _fetch_requests(self, url: str) -> str:
        if self._fetcher is not None:
            return self._fetcher(url)
        if requests is None:
            raise JijiScrapeError("requests is not installed")
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        except Exception as exc:
            raise JijiScrapeError(f"Jiji fetch failed for {url}: {exc}") from exc
        if resp.status_code in (403, 503) or _is_challenge_text(resp.text):
            raise JijiScrapeError("Jiji returned a challenge/block page (HTTP %s). Do not retry aggressively — try again later or open the page manually." % resp.status_code)
        if resp.status_code != 200:
            raise JijiScrapeError(f"Jiji returned HTTP {resp.status_code} for {url}")
        return resp.text

    def _fetch_browser(self, url: str) -> str:
        if self.browser_fetcher is not None:
            return self.browser_fetcher(url)
        from .browser_fetch import default_profile_dir, fetch_with_browser

        profile = self.profile_dir or default_profile_dir(self.data_dir)
        return fetch_with_browser(url, profile_dir=profile, data_dir=self.data_dir)

    def search_url(self, query: str) -> str:
        import urllib.parse
        return JIJI_CV_SEARCH.format(query=urllib.parse.quote_plus(query))

    # ---- parsing (pure HTML -> dicts, no network) ----
    def parse_cv_list_html(self, html: str) -> list[dict]:
        """Extract CV card links from a listing page.

        Listing cards are <a> tags whose href points at jiji.ng.
        Fails fast when no cards are found (structure change), instead
        of silently returning 'no CVs'.
        """
        if BeautifulSoup is None:
            raise JijiScrapeError("beautifulsoup4 is not installed")
        soup = BeautifulSoup(html, "html.parser")
        cards: list[dict] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "jiji.ng" not in href and not href.startswith("/"):
                continue
            text = " ".join(a.get_text(" ", strip=True).split())
            if len(text) < 3:
                continue
            url = href if href.startswith("http") else JIJI_BASE + href
            if "/seeking-work" not in url and "-cv" not in url and "cv" not in url.lower():
                # Still keep jiji.ng links: listing pages vary; title text decides.
                pass
            cards.append({"title": text, "cv_url": url})
        # Dedupe by URL, keep order.
        seen, out = set(), []
        for c in cards:
            if c["cv_url"] not in seen:
                seen.add(c["cv_url"])
                out.append(c)
        if not out:
            raise JijiScrapeError("Jiji page structure changed: no CV cards found (no jiji.ng links)")
        return out

    def parse_cv_detail_html(self, html: str, url: str = "") -> dict:
        """Parse one CV detail page into structured fields."""
        if BeautifulSoup is None:
            raise JijiScrapeError("beautifulsoup4 is not installed")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n")
        fields: dict[str, str] = {"cv_url": url, "source": "jiji"}
        # Title: first h1, else <title>.
        h1 = soup.find("h1")
        fields["title"] = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else "")
        # Labelled fields: "Label: value" lines.
        for line in text.splitlines():
            line = " ".join(line.split())
            for label in FIELD_LABELS:
                if line.lower().startswith(label.lower() + ":"):
                    fields[label.lower().replace(" ", "_")] = line.split(":", 1)[1].strip()
        # Name: heuristic — element with class containing 'name'/'seller'.
        name_el = soup.find(class_=re.compile(r"(name|seller|owner)", re.I))
        if name_el:
            fields["name"] = name_el.get_text(" ", strip=True)[:120]
        # Phone: only if the page itself exposes it publicly in text.
        m = re.search(r"(\+?234[\d\s\-()]{7,}|0\d{10})", text)
        if m:
            fields["phone"] = re.sub(r"[\s\-()]", "", m.group(1))
        # Experience years from experience text.
        exp = fields.get("previous_work_experience", "")
        ym = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", exp or "", re.I)
        fields["experience_years"] = float(ym.group(1)) if ym else None
        # Expected salary number.
        sal = fields.get("expected_salary", "")
        sm = re.search(r"(\d[\d,]*)", sal or "")
        fields["expected_salary_min"] = int(sm.group(1).replace(",", "")) if sm else None
        # Normalise keys to candidate-dict shape.
        fields.setdefault("skills", "")
        fields.setdefault("location", "")
        fields.setdefault("education", "")
        fields.setdefault("highest_qualification", "")
        fields.setdefault("languages", "")
        fields.setdefault("certifications", "")
        fields.setdefault("employment_status", "")
        fields.setdefault("job_type", "")
        fields.setdefault("name", "")
        fields.setdefault("phone", "")
        fields["experience_text"] = fields.pop("previous_work_experience", "")
        fields["expected_salary"] = fields.get("expected_salary", "")
        return fields
