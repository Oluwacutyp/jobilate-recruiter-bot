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

Long digests are sent in ≤4000-char parts (Telegram's limit is 4096),
never rejected as "Message is too long" — `/harvest`, `/dump`, `/export`,
live push, and long lists all chunk the same way.

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

## Cloudflare fallback chain — "Verify you're human" / "Just a moment..."

Jiji sits behind Cloudflare. The bot uses a FIRST-CLASS fallback
chain with more than one fallback (user-approved 2026-10-14):

1. **requests + CF_CLEARANCE + Edge UA** — the fast path. If
   `CF_CLEARANCE` is set in `.env`, requests sends it as a cookie
   with the Edge User-Agent (same browser + same RDP + same UA that
   solved it, or Cloudflare may reject the cookie).
2. **Playwright real Microsoft Edge + stealth + CF_CLEARANCE** — on a
   challenge/block page, the bot falls back ONCE per URL to real Edge
   (`channel="msedge"`, fallback Chrome → Chromium if Edge is not
   installed), with a stealth init script (hides `navigator.webdriver`,
   spoofs `window.chrome` / plugins / languages / permissions — no
   solving services, no token forgery), small human-like behaviour
   (pause, mouse move, slow scroll), and the `cf_clearance` cookie in
   the browser context. It clicks the Turnstile checkbox if one is
   present, and polls up to 30s for the automatic "Just a moment..."
   check to clear (there is nothing to click on that page — the
   browser must pass the automatic check).
3. **Clear human handoff error** — if both fail: "Cloudflare 'Just a
   moment...' challenge — solve in Edge, update CF_CLEARANCE in
   .env, retry." Never a fake result.

Why real Edge, not Playwright's Chromium? User-verified 2026-10-14:
same RDP, same IP — real Edge passes Cloudflare, bot's Playwright
Chromium gets "Just a moment...". That proves it is automation
fingerprinting, not IP blocking alone. Edge passes because it is a
real browser + human signals; Playwright's bundled Chromium is
detected. Edge is preinstalled on Windows RDP — no extra install.

### CF_CLEARANCE handoff (if you solve it in Edge)

Yes — if you solve it, the bot reuses your cookie. Steps on the RDP:

1. In **Microsoft Edge** on the RDP, open `https://jiji.ng/seeking-work-cvs`,
   wait for it to load past "Just a moment..." (no checkbox needed).
2. Press `F12` → **Application** tab → **Cookies** → `https://jiji.ng`
   → copy the **`cf_clearance`** cookie **Value**.
3. In the bot folder, edit `.env` and add:
   ```text
   CF_CLEARANCE=<paste the value here>
   ```
4. Save. **No restart needed** — the bot re-reads `.env` on EVERY
   scrape (both requests and Playwright), so the new cookie is used
   on the next `/scrape`. Never share the value, never paste it in
   Telegram — it is a session cookie, and the bot never logs it and
   never puts it in error messages.
5. Use the **same Edge + same RDP (same IP + same UA)** that solved
   it. The bot uses `JIJI_USER_AGENT` (default: Edge UA) for BOTH
   requests and Playwright, so the cookie matches. If you solve in a
   different browser / machine / IP, Cloudflare may reject the cookie.

**Expiry:** `cf_clearance` typically expires in ~30min–2h (sometimes
longer — one user-verified cookie lasted a year). When it expires you
will see the Cloudflare error again — just re-solve in Edge + update
`.env` (no restart needed).

### Troubleshooting CF_CLEARANCE — `/config` tells you if the bot sees it

After `git pull` + restart, send `/config` in Telegram. It shows
(without ever showing the value):

```text
CF_CLEARANCE: set (len 213, from .env file)
JIJI_USER_AGENT: Mozilla/5.0 ... Edg/131.0.0.0
.env path checked: C:\jobilate-recruiter-bot\.env
BROWSER_CHANNELS: msedge → chrome → Chromium
```

If `/config` says `CF_CLEARANCE: NOT SET` even though you added it,
check these (in order):

1. **Filename must be exactly `.env`.** Notepad's default "Save as
   type: Text Documents" saves it as **`.env.txt`** — and the bot
   ignores `.env.txt` on purpose. Fix: in Notepad use
   File → Save As → "Save as type: **All Files**" → filename `.env`.
2. **One line, no breaks, no quotes, no spaces around `=`.**
   `CF_CLEARANCE=<long value>` on a single line. A line break in the
   middle truncates it and Cloudflare rejects it.
3. **User-Agent must match the Edge that solved it.** The cookie was
   solved with a specific Edge version (e.g. Edge 155). The bot's
   default UA is Edge 131. If your Edge is newer, copy your exact UA
   from `edge://version` (the "User Agent" line) and set in `.env`:
   ```text
   JIJI_USER_AGENT=<exact UA from edge://version>
   ```
   No restart needed — the bot re-reads `.env` on every scrape.
4. **No restart needed after a `.env` edit** (bot re-reads `.env`
   on every scrape). Verify with `/config` — it should flip to
   `CF_CLEARANCE: set`. You do NOT need to "load the env first".

Windows RDP steps (one-time):
```powershell
pip install -r requirements.txt
playwright install msedge
```
Then `git pull`, restart the bot, and `/scrape 2` to retry. If the
challenge still shows, wait + retry — the bot never retries
aggressively and never fakes results. Set `PLAYWRIGHT_ENABLED=0`
in `.env` to disable the browser fallback (requests only).
`PLAYWRIGHT_HEADLESS` defaults to headed (0) on Windows for the best
pass rate, headless (1) elsewhere. See `/config` and `/limits`.

Implementation note: the Playwright Sync API cannot run on the
Telegram bot's asyncio event-loop thread ("Sync API inside the asyncio
loop"). The bot therefore runs the whole sync scrape — including the
browser fallback — in `asyncio.to_thread` (a worker thread with no
running loop) via `scrape_one_vacancy_async` / `scrape_all_active_async`
/ `JijiScraper.fetch_async`. Sync callers keep the sync versions.

Error classification: a "Just a moment..." / "Checking your browser"
page is reported as a Cloudflare block (with a short diagnostic:
`diag: title=... anchors=N html_len=N flags=...`), NEVER as "page
structure changed".

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
- **Global catch-all pass.** After the category passes, the bot runs ONE
  global search — query = short title + location, NO category — which
  spans ALL Jiji categories. A qualified candidate posted outside the
  expected categories (e.g. a B.Tech + 5y vet-drug-sales CV under
  "Management") is still found. Global hits are scored with the same
  matching (category-agnostic), deduped against category hits, and
  count toward the SAME max-cards-per-vacancy cap (skipped when the cap
  is already reached). No hardcoded adjacent-category list — the global
  search is the dynamic catch-all.
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
| `PLAYWRIGHT_ENABLED` | Browser fallback (default 1, 0 = requests only) |
| `PLAYWRIGHT_HEADLESS` | 0 = headed (default on Windows), 1 = headless |
| `BROWSER_PROFILE_DIR` | Verified browser session (default `DATA_DIR/browser_profile`) |
| `CF_CLEARANCE` | Human-verified Cloudflare cookie from Edge (re-read from `.env` each scrape, no restart needed; expires ~30min–2h; never logged) |
| `JIJI_USER_AGENT` | UA for both requests + Playwright (default: Edge UA — must match the Edge that solved the cookie) |
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
