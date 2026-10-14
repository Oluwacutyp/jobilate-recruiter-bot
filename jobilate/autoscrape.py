"""Auto-scrape loop + shared helpers for the additive UX batch.

ADDITIVE ONLY (2026-10-14): nothing here replaces existing behaviour.
- Auto-scrape: background loop that scrapes ACTIVE vacancies, scores,
  dedups, stores, and live-pushes new matches to the recruiter chat.
- Morning to-do: once a day at the configured hour, send the to-do.
- Reply keyboard layout + button mapping (pure data, no Telegram import
  needed for the layout itself).
- Short help text (bare /help) — the full HELP_TEXT is unchanged.
- Just-paste vacancy detection (conservative heuristic).
- /howto fallback text (used only when MESSAGE_TO_HER.md is missing).

HARD LIMIT: every send goes to the recruiter chat only, via
guard_recipient in telegram_bot. Nothing here contacts candidates.
"""
from __future__ import annotations

from datetime import datetime

from .matching import categories_for_title, score_candidate
from .models import Candidate

# ---------------------------------------------------------------------------
# Reply keyboard (persistent bottom buttons) — pure data layout.
# ---------------------------------------------------------------------------
REPLY_KEYBOARD_LAYOUT: list[list[str]] = [
    ["➕ Add Vacancy", "📋 My Vacancies"],
    ["📥 Harvest", "📝 To-Do"],
    ["📊 Status", "❓ How to use"],
]

# Button label -> command name (same logic as the /command).
REPLY_BUTTON_ACTIONS: dict[str, str] = {
    "➕ Add Vacancy": "newvacancy",
    "📋 My Vacancies": "vacancies",
    "📥 Harvest": "harvest",
    "📝 To-Do": "todo",
    "📊 Status": "status",
    "❓ How to use": "howto",
}


def build_reply_keyboard():
    """ReplyKeyboardMarkup with the 6 bottom buttons (imports telegram lazily)."""
    from telegram import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        [[KeyboardButton(text=label) for label in row] for row in REPLY_KEYBOARD_LAYOUT],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def build_reply_keyboard_remove():
    """ReplyKeyboardRemove — hides the bottom buttons."""
    from telegram import ReplyKeyboardRemove

    return ReplyKeyboardRemove()


# ---------------------------------------------------------------------------
# Short help (bare /help). Full HELP_TEXT in telegram_bot is unchanged.
# ---------------------------------------------------------------------------
SHORT_HELP_TEXT = """Jobilate Recruiter Bot 🤝 — quick start:

Tap the buttons below, or type:
 /newvacancy — add a vacancy (wizard, or paste the full text)
 /vacancies — list your vacancies
 /harvest — get new candidates + CSV + ZIP
 /todo — today's to-do + follow-ups
 /status — see all vacancies
 /howto — full guide, in this chat
 /scrape — scrape Jiji now for active vacancies

The bot finds CVs and sends them to YOU. You text candidates yourself.
Type /help all for the full command list."""


# ---------------------------------------------------------------------------
# /howto fallback (used only when MESSAGE_TO_HER.md cannot be read).
# ---------------------------------------------------------------------------
HOWTO_FALLBACK = """Jobilate Recruiter Bot — how to use it:

1. Add a vacancy: /newvacancy (wizard), or paste the whole vacancy
   in one message after /newvacancy. You can also just paste a vacancy
   with no command at all — the bot will ask if it is a new vacancy.
2. The bot scrapes Jiji CVs by itself and sends you new matches
   automatically (card + CV file). Or send /harvest any time.
3. Text candidates yourself on WhatsApp. The bot never texts them.
4. Mark them: tap the buttons on a card, or /mark <vacancy> <candidate>
   <Texted|Interested|No reply|Not fit|Sent to employer>.
5. /todo each morning shows new + follow-ups due.
6. /school on pauses everything (busy mode). /school off resumes.
7. Tap the buttons at the bottom — same as typing the commands.
"""


# ---------------------------------------------------------------------------
# Just-paste vacancy detection (conservative — must look like a vacancy).
# ---------------------------------------------------------------------------
VACANCY_KEYWORDS = ("vacancy", "salary", "₦", "requirements", "location", "years", "experience", "job")


def looks_like_vacancy(text: str) -> bool:
    """True for long texts with >=2 vacancy keywords.

    Short chat ("hi", "ok", "yes") never matches. A pasted vacancy
    (100+ chars, several keywords) matches.
    """
    t = (text or "")
    if len(t) < 100:
        return False
    low = t.lower()
    hits = sum(1 for kw in VACANCY_KEYWORDS if kw in low)
    return hits >= 2


# ---------------------------------------------------------------------------
# Morning to-do scheduling.
# ---------------------------------------------------------------------------
def should_send_todo(now: datetime, todo_hour: int, last_todo_date: str, school_mode: bool) -> bool:
    """True once a day at todo_hour, unless school mode is on."""
    if school_mode:
        return False
    if now.hour != todo_hour:
        return False
    return (last_todo_date or "") != now.date().isoformat()


# ---------------------------------------------------------------------------
# Search-query sanitisation (2026-10-14): a vacancy title once got saved
# as the FULL pasted vacancy text (multi-line, multi-KB). Building a
# Jiji query from that produced a giant useless URL and a giant error
# bubble. Search queries now use ONLY the short first-line title +
# category + location, capped at 120 chars. NEVER raw_text/requirements.
# ---------------------------------------------------------------------------
def short_search_title(title: str) -> str:
    """First line of a title, stripped, max 80 chars. Never multi-line."""
    title = (title or "")
    first = title.splitlines()[0].strip() if title.strip() else ""
    return first[:80]


def build_search_query(vacancy_title: str, category: str, location: str = "") -> str:
    """Short Jiji query: '<short title> <category> <location>', ≤120 chars."""
    parts = [short_search_title(vacancy_title)]
    if (category or "").strip():
        parts.append((category or "").strip())
    if (location or "").strip():
        parts.append((location or "").strip())
    return " ".join(parts)[:120]


def build_global_search_query(vacancy_title: str, location: str = "") -> str:
    """Global catch-all query: '<short title> <location>', NO category, ≤120 chars.

    Hits the global seeking-work-cvs listing, which spans ALL categories,
    so a qualified candidate posted outside the expected categories is
    still found. Matching stays category-agnostic (scores by
    education/years/skills/location, not by category), so global hits are
    scored exactly like category hits.
    """
    return build_search_query(vacancy_title, "", location)


def short_vacancy_label(vacancy) -> str:
    """Short label for error messages: '#<id> <short title>'."""
    vid = getattr(vacancy, "id", "?")
    return f"#{vid} {short_search_title(getattr(vacancy, 'title', ''))}"


def _is_block_error(msg: str) -> bool:
    """True for real Jiji block/challenge errors (abort, don't hammer)."""
    low = (msg or "").lower()
    return any(
        token in low
        for token in ("challenge", "403", "503", "blocked", "turnstile", "verify you are human", "verify you're human")
    )


def truncate_error(err: str | None, limit: int = 500) -> str | None:
    """Cap an error string for Telegram (full cause stays in logs)."""
    if err is None:
        return None
    err = str(err)
    if len(err) <= limit:
        return err
    return err[:limit] + "..."


# ---------------------------------------------------------------------------
# Scraping one vacancy / all active vacancies (pure store + scraper).
# ---------------------------------------------------------------------------
def scrape_one_vacancy(store, vacancy, scraper, max_cards: int = 20) -> tuple[list[dict], str | None]:
    """Scrape one vacancy, store new matches, return (new_links, error).

    Error is None on success. A Jiji block / structure change returns an
    error string instead of raising, so the caller can notify once and
    keep going with other vacancies. One bad CV detail page is skipped,
    not fatal.
    """
    from .scraper import JijiScrapeError

    existing_ids = {ln.get("candidate_id") for ln in store.links_for_vacancy(vacancy.id)}
    # Sanitised title for BOTH search + scoring: a corrupted multi-line
    # title must never leak into a query or into token overlap.
    search_title = short_search_title(vacancy.title)
    vac = {
        "title": search_title,
        "location": vacancy.location,
        "pay_min": vacancy.pay_min,
        "requirements_text": vacancy.requirements_text,
        "education_required": vacancy.education_required,
        "min_years": vacancy.min_years,
    }
    new_cids: set[int] = set()
    try:
        categories = categories_for_title(search_title)
        cards: list[dict] = []
        # Per-category resilience (2026-10-14): one category returning
        # 0 results must NOT kill the whole vacancy — the next category
        # may have results (verified live: "farming & veterinary +
        # Lagos" -> 0 results, "sales + Lagos" -> 47 results). A real
        # block aborts immediately (no point hammering); structure
        # errors are collected and only surface if NO category yields cards.
        block_error: str | None = None
        structure_errors: list[str] = []
        for cat in categories:
            try:
                url = scraper.search_url(build_search_query(search_title, cat, vacancy.location))
                html = scraper.fetch(url)
                cards.extend(scraper.parse_cv_list_html(html))
            except JijiScrapeError as exc:
                if _is_block_error(str(exc)):
                    block_error = str(exc)
                    break
                structure_errors.append(str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 - one category failing must not kill the run
                structure_errors.append(f"Scrape failed for {short_vacancy_label(vacancy)}: {exc}")
                continue
            if len(cards) >= max_cards:
                break
        # Global catch-all pass (ADDITIVE 2026-10-14): category searches
        # miss qualified candidates posted outside the expected
        # categories (e.g. a B.Tech + 5y vet-drug-sales CV posted under
        # "Management" or "General"). One global search (title +
        # location, NO category) spans ALL categories. It runs AFTER the
        # category passes (most relevant first), counts toward the SAME
        # max_cards cap (skipped when already reached), reuses the same
        # fetch/parse/scoring/dedup, and follows the same resilience:
        # 0-results -> done, real block -> abort, no hammering. No
        # hardcoded adjacent-category list — the global search IS the
        # dynamic catch-all.
        if block_error is None and len(cards) < max_cards:
            try:
                global_url = scraper.search_url(
                    build_global_search_query(search_title, vacancy.location)
                )
                global_html = scraper.fetch(global_url)
                global_cards = scraper.parse_cv_list_html(global_html)
                seen_global: set[str] = {c.get("cv_url", "") for c in cards}
                for gc in global_cards:
                    if gc.get("cv_url", "") not in seen_global:
                        cards.append(gc)
                        seen_global.add(gc.get("cv_url", ""))
            except JijiScrapeError as exc:
                if _is_block_error(str(exc)):
                    # Real block on the global pass: keep category cards
                    # if any; only surface as the error when no cards.
                    if not cards:
                        block_error = str(exc)
                else:
                    structure_errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001 - global pass must not kill category results
                structure_errors.append(f"Scrape failed for {short_vacancy_label(vacancy)}: {exc}")
        if not cards:
            if block_error is not None:
                return [], truncate_error(block_error)
            if structure_errors:
                return [], truncate_error(structure_errors[0])
            # Every category + the global pass returned 0 results
            # (parse returned []) -> no new candidates, NOT an error.
            return [], None
        seen_urls: set[str] = set()
        for card in cards[:max_cards]:
            url = card.get("cv_url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                detail_html = scraper.fetch(url)
                cv = scraper.parse_cv_detail_html(detail_html, url)
            except Exception:  # noqa: BLE001 - one bad CV page is skipped
                continue
            cand = Candidate(
                name=cv.get("name", "") or card.get("title", ""),
                phone=cv.get("phone", ""),
                title=cv.get("title", "") or card.get("title", ""),
                job_type=cv.get("job_type", ""),
                employment_status=cv.get("employment_status", ""),
                education=cv.get("education", ""),
                highest_qualification=cv.get("highest_qualification", ""),
                skills=cv.get("skills", ""),
                languages=cv.get("languages", ""),
                certifications=cv.get("certifications", ""),
                experience_text=cv.get("experience_text", ""),
                experience_years=cv.get("experience_years"),
                expected_salary=cv.get("expected_salary", ""),
                expected_salary_min=cv.get("expected_salary_min"),
                location=cv.get("location", ""),
                cv_url=cv.get("cv_url", url),
                source="jiji",
            )
            cid = store.add_or_get_candidate(cand)
            if cid in existing_ids or cid in new_cids:
                continue
            score, tier, reason = score_candidate(vac, {k: getattr(cand, k) for k in (
                "name", "phone", "title", "job_type", "employment_status", "education",
                "highest_qualification", "skills", "languages", "certifications",
                "experience_text", "experience_years", "expected_salary",
                "expected_salary_min", "location", "cv_url", "source")})
            store.link_candidate(vacancy.id, cid, score, tier, reason)
            new_cids.add(cid)
    except JijiScrapeError as exc:
        return [], truncate_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - loop must survive unexpected errors
        return [], truncate_error(f"Scrape failed for {short_vacancy_label(vacancy)}: {exc}")
    if not new_cids:
        return [], None
    links = [ln for ln in store.links_for_vacancy(vacancy.id) if ln.get("candidate_id") in new_cids]
    return links, None


async def scrape_one_vacancy_async(store, vacancy, scraper, max_cards: int = 20) -> tuple[list[dict], str | None]:
    """Async-safe wrapper for Telegram handlers (async context).

    Runs the sync ``scrape_one_vacancy`` (which may invoke the Playwright
    Sync API via the scraper) in ``asyncio.to_thread`` — a worker thread
    with no running loop, so the Sync API works and the event loop is
    never blocked by requests/sleeps. Sync callers keep the sync version.
    """
    import asyncio

    return await asyncio.to_thread(scrape_one_vacancy, store, vacancy, scraper, max_cards)


def scrape_all_active(store, scraper, max_cards: int = 20) -> tuple[dict[int, list[dict]], list[str]]:
    """Scrape every ACTIVE vacancy. Returns ({vacancy_id: new_links}, errors)."""
    per_vacancy: dict[int, list[dict]] = {}
    errors: list[str] = []
    for v in store.list_vacancies(status="active"):
        new_links, err = scrape_one_vacancy(store, v, scraper, max_cards=max_cards)
        if new_links:
            per_vacancy[v.id] = new_links
        if err:
            errors.append(err)
    return per_vacancy, errors


async def scrape_all_active_async(store, scraper, max_cards: int = 20) -> tuple[dict[int, list[dict]], list[str]]:
    """Async-safe wrapper for Telegram handlers (see scrape_one_vacancy_async)."""
    import asyncio

    return await asyncio.to_thread(scrape_all_active, store, scraper, max_cards)


def dedup_new_links(links: list[dict]) -> list[dict]:
    """Dedupe link dicts by candidate_id (helper for tests / callers)."""
    seen: set = set()
    out: list[dict] = []
    for ln in links:
        key = ln.get("candidate_id", ln.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(ln)
    return out
