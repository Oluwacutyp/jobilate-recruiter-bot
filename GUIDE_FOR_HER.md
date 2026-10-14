# Guide for Her — Jobilate Recruiter Bot 💼

Hello! This bot helps you find CVs. It never texts candidates.
You text them yourself. That never changes.

## 1. Add a vacancy

Send `/newvacancy` to the bot.

The bot will ask you, one step at a time:

1. Role — example: `Sales Supervisor`
2. Location — example: `Lagos State`
3. Pay — example: `₦500,000+/month`
4. Requirements — example: `B.Tech Animal Production and Health, 5+ years agro-pharma sales (vet drugs), connections with feed millers and farms, team leadership, willing to travel`
5. Employer — example: `Agro-Pharmaceuticals company`
6. Deadline — example: `2026-10-31` or `none`
7. Contact — who should candidates reach

Then it shows you what it read. Reply `YES` to save.

Short cut: you can also paste the whole vacancy in one message
after `/newvacancy`. The bot will read it and ask you to confirm.

If you send a photo or a voice note, the bot will ask you to
send it as text. It cannot read photos. Just type or paste the text.

## 2. Read a candidate card

When the bot finds a CV, it sends you a card like this:

> Tier1 · Adaeze — Sales Supervisor
> Phone number · Lagos State
> Why: education match, 6 years experience, role fit
> CV: link

- **Tier1** means strong match. **Tier2** means good on one side.
  **Tier3** means vague or unknown — still worth a look, after Tier1 and Tier2.
- **Why** tells you why the bot picked this person.
- The phone number is on the card. Copy it. You text the person yourself.
- Each new card also comes with that person's CV file (a `.txt` file).
  Open it to read the full CV. Batched cards come with one ZIP instead,
  holding all those CVs (see section 6b for how to unzip).

## 3. Text the candidate yourself

Use the fixed message. It never changes, except the job details.

Send `/template 1` (use your vacancy number) to see the message.
Copy it. Paste it in your own chat with the candidate.
Change only the job details: role, location, pay, requirements.

The bot never sends this message for you.

## 4. Mark the candidate

Tap a button on the card, or type:

- `/mark 1 5 Texted` — you texted them
- `/mark 1 5 Interested` — they are interested
- `/mark 1 5 No reply` — they did not reply
- `/mark 1 5 Not fit` — not a fit
- `/mark 1 5 Sent to employer` — you sent them to the employer

(Here `1` is the vacancy number and `5` is the candidate number.)

Marks matter. They show in your CSV, your stats, and your harvest.

## 5. Harvest vs Dump — get your list

- `/harvest` — sends you only the NEW candidates you have not
  seen yet, plus a CSV file + a ZIP file. Use this every day.
- `/harvest unsent` — candidates you have not texted yet.
- `/harvest unsent_employer` — candidates not yet sent to the employer.
- `/dump` — sends EVERYTHING. Only use it when you really need the full list.

Harvest always sends THREE things:
1. A readable list (the digest message) — scan it quickly.
2. A real CSV file — open it right now, no unzipping needed.
3. A ZIP file — the full pack: CSV copy + one CV file per candidate
   + a README that explains how to unzip.

## 6. Get a CSV + CV files + ZIP

- `/export 1` — digest + CSV + ZIP for vacancy 1.
- `/export` — digest + CSV + ZIP for all vacancies.
- `/shortlist 1` — only the Interested candidates for vacancy 1.

## 6b. How to unzip the ZIP (and read the CVs)

The ZIP holds one CV file per candidate, named like
`cv_7_Name.txt`. Each one is plain text — it opens on any phone.

- **Android:** tap the ZIP in Telegram → tap Extract, or open it with
  the Files app → long-press the ZIP → Extract. The CV files appear
  next to it. Tap any `.txt` to read it.
- **iPhone:** tap the ZIP → Preview → Share → Save to Files → open
  Files, long-press the ZIP → Uncompress.
- **Windows:** right-click the ZIP → Extract All → Extract.

If you only need the quick list, just open the CSV — no unzipping needed.

## 7. Start, stop, pause

- `/pause 1` — pause one vacancy. Others keep going.
- `/resume 1` — start it again.
- `/stop 1` — stop one vacancy.
- `/pauseall` — pause everything. `/resumeall` — start everything again.
- `/status` — see all vacancies and how many candidates each has.

## 8. Quiet hours and school mode

- Quiet hours: the bot will not push new cards late at night.
  Default is 10pm to 7am. Ask to change it if you need to.
- `/school on` — busy mode. Pauses everything.
- `/school off` — back to normal.

## 9. Daily to-do

Send `/todo` any morning. It shows:

- New candidates to review
- People you have not texted yet
- Follow-ups due (you texted them 3 or more days ago, no reply)

## 10. If something looks wrong

- Wrong vacancy details? `/edit 1 pay_text=₦600,000` (change what you need).
- Wrong candidate? `/block 5` hides them. `/unblock 5` brings them back.
- Bot sent too much? `/live 1 off` turns off live push for vacancy 1.
  You will still get everything with `/harvest`.
- Still wrong? Send `/status` and tell the person who set up the bot
  what you see. Do not share your bot token or passwords with anyone.

## Quick list

`/newvacancy` · `/vacancies` · `/candidates 1` · `/template 1` ·
`/mark 1 5 Texted` · `/harvest` · `/export 1` · `/todo` · `/help`

You are in control. The bot finds. You decide. You text. 🤝
