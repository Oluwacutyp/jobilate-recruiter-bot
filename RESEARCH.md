# Research notes (grounded, no invented APIs)

## Framework: python-telegram-bot (PTB) v20+ — chosen

From the Devon Telegram frameworks audit
(`~/workspace/reports/telegram-bot-frameworks-audit.md`, 2026-10-07):

- **PTB** (~29.3k stars, biggest community): pure asyncio + httpx since
  v20, `Application` + `ConversationHandler` (battle-tested FSM for the
  `/newvacancy` wizard), inline keyboards + `CallbackQueryHandler`,
  built-in `AIORateLimiter` (v21), `PicklePersistence`/`DictPersistence`.
  Best docs + biggest example folder. Works on Windows RDP + Termux,
  zero $ cost.
- **aiogram v3** (~5.8k stars): cleaner Router/Dispatcher + typed
  `CallbackData`, first-class FSM with Redis storage — but no built-in
  throttle in v3 (needs middleware), smaller community. Good alternative;
  PTB wins here on community size, ConversationHandler fit, and
  single-file deploy simplicity for a phone-first recruiter bot.
- Telegraf / grammY are Node.js — rejected (Python stack, Termux fit).
- Pyrogram is ARCHIVED — rejected. Telethon is MTProto (user accounts),
  not Bot API — rejected for a bot.

Decision: **PTB v20+**, `ApplicationBuilder`, `ConversationHandler`
for the wizard, `CallbackQueryHandler` for one-tap marks.

## Jiji — no API, scrape public HTML only

Grounded in Devon's Jiji connector (`nomorals/connectors/jiji.py`,
verified 2026-10-02) and its tests:

- **No official API.** Jiji publishes no search/listings/seller API.
  Everything is rendered-DOM scraping of the public site.
- **No automated seller contact or login.** Devon reaches sellers only
  via human-in-the-loop; this bot goes further — it NEVER contacts
  candidates at all.
- **Rate limit: ≥3s between page loads** (`_MIN_REQUEST_GAP_S = 3.0`),
  enforced in this bot's `JijiScraper`.
- **Cache TTL 15 min** (`_CACHE_TTL_S = 15*60`), same here.
- **Listing cards are `<a>` tags with jiji.ng URLs**
  (`https://jiji.ng/<location>/<category>/<slug>-<id>.html`); price/title/
  location split out of card text. This bot's `parse_cv_list_html`
  follows the same rule: find `<a href>` pointing at jiji.ng.
- **Price parsing:** Jiji shows "contact / swap / exchange" instead of
  a numeric price on some cards — this bot treats missing numbers as
  unknown, never as zero.
- **Cloudflare:** plain HTTP fetch gets a 403 challenge page on Jiji;
  only a real JS browser passes (Devon uses rendered browser tabs).
  This bot's scraper uses `requests` + BeautifulSoup for the MVP and
  **fails fast** with a clear error on a challenge/block page instead
  of returning fake empty results. If Jiji blocks plain fetches in
  production, the honest path is: open the page manually in a browser
  (or wire a rendered-browser fetch later) — never fake results, never
  hammer retries.
- **CV structure** (Seeking Work – CV pages): Job Type, Employment
  Status, Education, Highest Qualification, Skills, Languages,
  Certifications, Previous Work Experience, Expected Salary, Location.
  `parse_cv_detail_html` extracts these labelled fields.

## CSV / harvest pattern

Harvest is incremental by flag, not by re-sending everything:
`harvested_to_her`, `sent_by_her`, `sent_to_employer` live on the
vacancy↔candidate link row. `/harvest` picks unharvested rows, sends
digest + real CSV, then marks them harvested. `/dump` = everything.
Same pattern as Devon's digest+attachment exports: readable message
first, real file attached.

## Concurrent vacancy pattern

One global scrape budget (shared rate limiter + cache in `JijiScraper`),
per-vacancy state (status, queue, stats, CSV, harvest flags) in SQLite.
Cross-vacancy dedup via a stable candidate key (normalised phone, else
name+title): one candidate row, many link rows. Pause/stop touches one
vacancy's status only.
