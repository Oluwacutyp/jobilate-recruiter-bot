# Jobilate Recruiter Bot — Locked Spec (condensed)

## Loop
1. Vacancy in via Telegram (`/newvacancy` wizard + paste/forward).
2. Scrape Jiji Seeking Work – CVs by job specs (public pages only, NO login).
3. Deliver number + CV to recruiter via Telegram (deduped, scored, match reason).
4. SHE texts on WhatsApp with the fixed template (template fixed, only job openings change).
5. She marks candidates in Telegram; bot tracks.

## Hard limit
BOT NEVER TEXTS CANDIDATES. No WhatsApp sending, no Jiji chat, no SMS,
no candidate messaging. Bot only scrapes, delivers to recruiter, tracks.
Guard: `guard_recipient` in `telegram_bot.py` raises for any non-recruiter chat.

## Sample 1 vacancy (example + test fixture)
Sales Supervisor, Agro-Pharmaceuticals, Lagos State, Full-Time, ₦500,000+/month.
Requires B.Tech/B.Agric/HND Animal Production and Health or B.Sc Animal Health
Technology, 5+ years agro-pharma sales (vet drugs), connections with feed
millers / commercial farms / agro-dealers / distributors, team leadership,
willing to travel.

## Jiji CV fields
Job Type, Employment Status, Education, Highest Qualification, Skills,
Languages, Certifications, Previous Work Experience, Expected Salary, Location.

## Matching
- Category-level first (Housekeeping covers cleaner/housekeeper/nanny…).
- Synonym / related-role expansion.
- Structured-field matching (education / experience / skills).
- Location tolerance; broad recall (weak matches still included, Tier3).
- Tiers: Tier1 = education + 5y + domain fit; Tier2 = one side strong;
  Tier3 = vague/unknown — still included, after Tier1/2.
- Vague WITH clear qualifications → scrape by qualifications.
  Vague WITHOUT → broad + label "broad match — review".
  Too vague to scrape → ask 1 clarifying question.
- Cross-category for senior roles (Sample 1: Farming & Veterinary +
  Sales & Telemarketing + Advertising & Marketing).
- Expected salary LOWER than vacancy pay does NOT disqualify.

## Simultaneous vacancies
Each vacancy is an independent job: own queue / stats / status / CSV / harvest.
Parallel scraping with a SHARED global scrape budget / rate limit.
Per-vacancy priority (High/Normal). Cross-vacancy dedup: one candidate
record, many vacancy links, tagged "also matches [Other]". Every card /
CSV / harvest tagged with vacancy ID + title. Pause/stop one does not
affect others.

## Live push (send-as-it-gets)
As a new match is found, send a card. Smart batching: Tier1 immediate,
rest batched every 5 min or every 5 new. Live pushes send CARD ONLY
(no CSV file each time — avoids spam) with note
"CSV updated — use /harvest for full CSV". Quiet hours respected.
Per-vacancy live on/off; global live-off = harvest-only.

## Digest + real CSV
`/harvest`, `/dump`, `/export`, daily digest send BOTH a readable digest
(Telegram message) + a real CSV file. Live pushes are card-only (exception above).

## Harvest
- `/harvest [vacancy]` incremental = only `harvested_to_her=False`, then mark harvested.
- `/harvest unsent` = `sent_by_her=False`.
- `/harvest unsent_employer` = `sent_to_employer=False`.
- `/harvest all` or `/dump` = everything.
- Bot never dumps by default.

## Marking
Texted / Interested / No reply / Not fit / Sent to employer
(via inline buttons + `/mark` command). Marks feed CSV / stats / harvest flags.

## Care features
Any-way vacancy input (paste/forward/text; screenshot/voice accepted as a
text placeholder with "send as text" note — NO fake OCR). One-tap marks.
CV digest cards with match reason. Daily to-do. Follow-up reminders
(texted N days ago, no reply). Employer pack (shortlist + CSV).
School/busy mode (pause-all). Quiet hours. Low-data (light messages).
Backup (ZIP of DB + CSVs). Privacy (contacts only to recruiter).
Transparency (match reason). Learning (Not fit down-weights similar —
future: used as a filter signal; currently marks are stored and surfaced).
Interview helper draft (checklist).

## CSV schema
`vacancy_id, vacancy_title, candidate_id, name, phone, candidate_title,
location, highest_qualification, experience_years, expected_salary, skills,
cv_url, score, tier, match_reason, mark, marked_at, sent_by_her,
sent_to_employer, harvested_to_her`
