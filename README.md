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

Demo without Telegram:

```bash
python run.py --once-vacancy-file /tmp/sample_vacancy.txt
```

## Commands

See `/help` in the bot, or `SPEC.md`. Highlights:
`/newvacancy` (wizard or paste) · `/vacancies` · `/start|/stop|/pause|/resume <id>` ·
`/candidates <id>` · `/mark <vacancy> <candidate> <Texted|Interested|No reply|Not fit|Sent to employer>` ·
`/harvest [vacancy|unsent|unsent_employer|all]` · `/dump` · `/export` · `/todo` · `/school on|off`

## Windows RDP deploy

1. On the Windows host: install Python 3.11+ (tick "Add python to PATH").
2. Copy this folder to e.g. `C:\jobilate-recruiter-bot`.
3. Double-click `scripts\deploy_rdp.bat` (or run `scripts\run_windows.ps1`).
   It creates `.venv`, installs requirements, copies `.env.example` → `.env`
   if missing, then runs `python run.py`.
4. Edit `.env` with the bot token + recruiter chat id, re-run the script.
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

## Layout

- `jobilate/` — real package: config, parser, matching, dedup, store (SQLite), CSV, scraper, live push, harvest, reminders, template, Telegram bot
- `tests/` — pytest suite incl. hard-limit scan
- `scripts/` — Windows deploy/run scripts

## Privacy

Candidate contacts go ONLY to the recruiter chat. Nothing is sent to
candidates, employers, or any other chat. Backup ZIPs contain the DB +
CSVs and are sent only to the recruiter.
