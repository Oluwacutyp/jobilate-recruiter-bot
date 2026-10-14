# Jobilate Recruiter Bot — MVP

Finds CVs on public Jiji "Seeking Work – CV" pages and delivers
number + CV to ONE recruiter over Telegram. She texts candidates
herself. The bot never contacts candidates.

## ⛔ HARD LIMIT (non-negotiable)

**BOT NEVER TEXTS CANDIDATES.** No WhatsApp sending, no Jiji chat,
no SMS, no candidate messaging of any kind. The bot ONLY:

1. Scrapes public Jiji Seeking Work – CV pages (no login)
2. Delivers number + CV to the recruiter via Telegram (deduped, scored, match reason)
3. Tracks marks, harvests, CSVs, reminders

Enforced in code: `jobilate/telegram_bot.py::guard_recipient` raises
unless the target chat IS the recruiter chat. `tests/test_hardlimit.py`
scans source for any candidate-outreach capability and fails if found.

## Quickstart

```bash
cp .env.example .env   # fill in BOT_TOKEN + ADMIN_CHAT_ID (yours only)
python -m venv .venv && .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py --dry-run
python run.py   # starts polling
```

`run.py` loads `.env` automatically (from the folder `run.py` lives in) —
you do NOT need to set env vars in PowerShell. Real env vars already set
in the session win over `.env`.

Demo without Telegram:

```bash
python run.py --once-vacancy-file /tmp/sample_vacancy.txt
```

## What you get on every delivery — digest + CSV + ZIP

Bulk sends (`/harvest`, `/dump`, `/export`) always deliver THREE things:
1. **Digest** — readable Telegram message, scan it quickly.
2. **Real CSV file** — opens right now, no unzipping needed. Full list in a table.
3. **ZIP file** — full pack: CSV copy + one CV `.txt` file per candidate
   (`cv_<candidate_id>_<name>.txt`, plain text, opens on any phone)
   + `README.txt` with how-to-unzip steps.

Live push: single new match → card + its CV `.txt` file. Batched matches →
one digest message + one ZIP with those CVs. If a ZIP would exceed 45MB,
the bot sends digest + CSV only + a plain note (text CVs are tiny, so
this is a safety cap, not the normal path).

How to unzip:
- **Android:** tap the ZIP in Telegram → Extract, or open it with the
  Files app → long-press the ZIP → Extract. The `.txt` CV files appear next to it.
- **iPhone:** tap the ZIP → Preview → Share → Save to Files → open Files,
  long-press the ZIP → Uncompress.
- **Windows:** right-click the ZIP → Extract All → Extract.

## Commands

Bare `/help` shows the short list; `/help all` shows everything.
See `SPEC.md` for the full list. Highlights:
`/newvacancy` (wizard or paste; aliases `/newvacancies`, `/addvacancy`) · `/vacancies` · `/start|/stop|/pause|/resume <id>` ·
`/candidates <id>` · `/mark <vacancy> <candidate> <Texted|Interested|No reply|Not fit|Sent to employer>` ·
`/harvest [vacancy|unsent|unsent_employer|all]` · `/dump` · `/export` · `/todo` · `/school on|off` ·
`/howto` (full guide in-chat) · `/scrape [id]` (scrape Jiji now) · `/keyboard on|off` (bottom buttons) · `/cancel` (exit the wizard)

## Easy ways to use it (no commands to memorise)

- **Buttons:** `/start` shows inline buttons (Add Vacancy, My Vacancies,
  Harvest, To-Do, How to use). The bottom of the chat always has the
  reply-keyboard buttons: Add Vacancy · My Vacancies · Harvest · To-Do ·
  Status · How to use. Tapping one is the same as typing its command.
  `/keyboard off` hides the bottom buttons; `/keyboard on` brings them back.
- **Just paste:** paste a vacancy as a plain message with no command —
  the bot asks "Is this a new vacancy?" with Yes/No buttons.
- **YES / NO buttons:** vacancy drafts show ✅ YES / ❌ NO buttons.
  Typing YES / NO still works exactly as before.
- **Auto-scrape (default ON):** every `SCRAPE_INTERVAL_MINUTES` (default
  30), the bot scrapes ACTIVE vacancies on Jiji by itself and pushes new
  matches to the recruiter chat (Tier1 immediately, rest batched).
  It respects quiet hours, school mode, and per-vacancy `/live` on/off.
  `/scrape [id]` triggers a scrape right now. `/demo` still exists for
  a demo match against sample CVs (no scraping).
- **Morning to-do (default 08:00):** the bot sends the daily to-do by
  itself once a day (new + follow-ups due), unless school mode is on.
  Change the hour with `/set todo_hour <0-23>`. `/todo` still works.
- **Re-sending `/newvacancy` while in the wizard** restarts the wizard
  instead of going quiet. `/cancel` always exits the wizard.

## Turnstile fallback (Playwright) — bot clicks "Verify you're human" itself

Jiji sometimes returns a Cloudflare Turnstile "Verify you're human"
checkbox page (HTTP 403) to the bot's `requests` fetches. The bot
tries `requests` first (fast, polite). On a challenge/block page it
falls back ONCE per URL to a real Chromium that clicks the checkbox
(a real browser click — no solving services, no token forgery) and
returns the resulting HTML, so the existing parsers work unchanged.

Why solving it in Chrome does NOT unblock the bot: Chrome and the
bot have separate cookies/fingerprints. The bot's own persistent
browser profile (`DATA_DIR/browser_profile`) holds the verified
session across runs — first run may need to verify, later runs reuse it.

Windows RDP steps (one-time):
```powershell
pip install -r requirements.txt
playwright install chromium
```
Then `git pull`, restart the bot, and `/scrape 1` to retry. If the
challenge still shows, wait + retry — the bot never retries
aggressively and never fakes results. Set `PLAYWRIGHT_ENABLED=0`
in `.env` to disable the fallback (requests only). `PLAYWRIGHT_HEADLESS`
defaults to headed (0) on Windows for the best Turnstile pass rate,
headless (1) elsewhere. See `/config` and `/limits` in the bot.

Implementation note: the Playwright Sync API cannot run on the
Telegram bot's asyncio event-loop thread ("Sync API inside the asyncio
loop"). The bot therefore runs the whole sync scrape — including the
browser fallback — in `asyncio.to_thread` (a worker thread with no
running loop) via `scrape_one_vacancy_async` / `scrape_all_active_async`
/ `JijiScraper.fetch_async`. Sync callers keep the sync versions.

## How Jiji pages are parsed (current structure, verified live 2026-10-14)

Jiji is a Nuxt app. Listing pages are server-rendered HTML: result
cards are `<a class="... qa-advert-list-item ...">` with hrefs like
`/<location>/<category>-cvs/<slug>-<id>.html?indexPosition=N`
(e.g. `/odeda/farming-and-veterinary-cvs/farm-manager-....html`).
The parser (`parse_cv_list_html`) prefers these card-shaped anchors.
The old generic fallback (any jiji.ng / relative link with text) is
kept for other listing layouts — nothing was deleted.

Two behaviours that matter:
- **0-results pages are NOT errors.** A search with no matches
  ("0 results for ...") legitimately has no card anchors — only home +
  Login/Registration links, which are never counted as cards. The parser
  returns `[]`, and the scrape loop moves on to the NEXT category
  instead of aborting the whole vacancy (one category returning 0
  results must not hide another category's 47 results).
- **Per-category resilience.** A real block (challenge/403/503) aborts
  immediately — no hammering. Other per-category failures are collected;
  they only surface if NO category yields cards. All-categories-0-results
  reports "No new matches", not "Jiji blocked".
- **Browser wait.** The Playwright fallback waits up to 10s for the
  card selector (`a.qa-advert-list-item, a[href*='-cvs/']`) so JS-rendered
  cards are present before the HTML is returned; 0-results pages return
  immediately (no wait burned). If no cards are found and the page is
  not a 0-results page, the error includes a SHORT diagnostic
  (`diag: title=... anchors=N html_len=N flags=...`) — no full HTML,
  no PII — so the Telegram message says WHAT page was fetched.

## If a vacancy title got saved as full text

On an older version, pasting a full vacancy as the wizard's Step 1
answer saved the WHOLE paste as the title, which produced giant search
URLs. The parser/wizard now treat a multi-line Step 1 paste as a pasted
vacancy (draft + confirm), and search queries use only the short
first-line title (≤120 chars). The DB is NOT auto-migrated — if an old
vacancy still has a full-text title, fix it with:
```
/vacancy 1
/edit 1 title=Sales Supervisor
```
then `/scrape 1` to retry. Error messages never include the full URL
— only the first 120 chars + "...". `/edit` accepts multi-word values
(`title=Sales Supervisor`, `location=Lagos State`) — values run to the
next `field=`.

## Windows RDP deploy

1. On the Windows host: install Python 3.11+ (tick "Add python to PATH").
2. Copy this folder to e.g. `C:\jobilate-recruiter-bot`.
3. Double-click `scripts\deploy_rdp.bat` (or run `scripts\run_windows.ps1`).
   It creates `.venv`, installs requirements, copies `.env.example` → `.env`
   if missing, then runs `python run.py`.
4. Edit `.env` with the bot token + recruiter chat id, re-run the script.
   `run.py` loads `.env` automatically — you do NOT need to set env vars
   in PowerShell.
5. Keep the window open (or run under a scheduled task) — polling needs the process alive.

## Termux note

Same steps with `python` on Termux: `pip install -r requirements.txt`,
set env vars, `python run.py`. Keep the session alive (e.g. `termux-wake-lock`).
No candidate messaging exists on any platform.

## Env vars

| Var | Meaning |
|---|---|
| `BOT_TOKEN` | Telegram bot token (secret, env only) |
| `ADMIN_CHAT_ID` | Recruiter's Telegram chat id — the ONLY chat the bot sends to |
| `DATA_DIR` | Where DB + CSVs live (default `./data`) |
| `QUIET_HOURS_START` / `QUIET_HOURS_END` | No live pushes in this window (default 22–07) |
| `SCRAPE_MIN_DELAY_SECONDS` | ≥3s between Jiji page loads |
| `CACHE_TTL_MINUTES` | Jiji page cache (default 15) |
| `PLAYWRIGHT_ENABLED` | Turnstile browser fallback (default 1, 0 = requests only) |
| `PLAYWRIGHT_HEADLESS` | 0 = headed (default on Windows), 1 = headless |
| `BROWSER_PROFILE_DIR` | Verified browser session (default `DATA_DIR/browser_profile`) |
| `SCRAPE_INTERVAL_MINUTES` | Auto-scrape loop interval (default 30, min 5) |
| `TODO_HOUR` | Hour the morning to-do is auto-sent (default 8) |

## Layout

- `jobilate/` — real package: config, parser, matching, dedup, store (SQLite), CSV, CV files + ZIP (`cv_files.py`), scraper, live push, harvest, reminders, template, Telegram bot
- `tests/` — pytest suite incl. hard-limit scan
- `scripts/` — Windows deploy/run scripts

## Privacy

Candidate contacts go ONLY to the recruiter chat. Nothing is sent to
candidates, employers, or any other chat. Backup ZIPs contain the DB +
CSVs + CV files and are sent only to the recruiter.
