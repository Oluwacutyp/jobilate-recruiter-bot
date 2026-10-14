# For her — from me

Hey, I made this bot for you so your work go easier. No stress.

The bot no go text anybody. Na you go text them yourself on WhatsApp. That one no go change.
The bot only do the hard part — find numbers + CVs, and send them to you.

Think of it as a template. We only have to be changing the job openings when necessary.

## How to use am

**0. You no need memorize commands**
Tap the buttons for bottom of the chat — Add Vacancy, My Vacancies, Harvest, To-Do, Status, How to use. Tap one, na same as typing the command.
If you need full guide inside Telegram, send `/howto`.

**1. Upload vacancy**
Send `/newvacancy` to the bot. `/newvacancies` and `/addvacancy` na same thing.
E go ask you one by one: role, location, pay, requirements, employer, deadline, contact.
Or you fit paste the whole vacancy at once. E go read am, show you wetin e understand, you go tap ✅ YES to save (or type YES — both work).
Easiest: just paste the vacancy as normal message, no command. Bot go ask "Is this a new vacancy?" — tap Yes.
If you get stuck for wizard, send `/cancel` and start again. If you send `/newvacancy` again, e go restart wizard.

**2. Bot go send you cards as e find new ones — by itself**
Bot go dey scrape Jiji by itself every 30 minutes and send you new matches automatically — you no need ask. `/scrape` go make am scrape now now.
As e see new CV wey match, e go send you card + the person CV file (na .txt, e go open for your phone).
Card go show: Tier1, name, phone number, location, why e match, CV link.
Tier1 na strong match. Tier2 na good for one side. Tier3 na vague — still look am after Tier1 and Tier2.
You go copy the number. You text the person yourself.

**3. Text them yourself**
Use the fixed message. E no dey change, except the job details.
Send `/template 1` to see am (1 na your vacancy number). Copy am, paste for your own chat with the person. Change only role, location, pay, requirements.
Bot no go send am for you.

**4. Mark them**
After you don text them, mark am so bot go remember:
Tap the button for the card, or type:
`/mark 1 5 Texted` — you don text them
`/mark 1 5 Interested` — them show interest
`/mark 1 5 No reply` — them no reply
`/mark 1 5 Not fit` — no be fit
`/mark 1 5 Sent to employer` — you don send them to employer
(1 na vacancy number, 5 na candidate number.)

**5. Harvest vs Dump**
`/harvest` — na only NEW ones wey you never see. E go send you 3 things: list + real CSV file + ZIP file. Use am every day.
`/harvest unsent` — only people you never text yet.
`/harvest unsent_employer` — only people you never send to employer yet.
`/dump` — EVERYTHING. Only use am when you really need full list.
Harvest always send 3 things: readable list to scan, real CSV to open now, ZIP with full CVs.

**6. CSV + CV files + ZIP**
`/export 1` — list + CSV + ZIP for vacancy 1.
`/export` — list + CSV + ZIP for all.
`/shortlist 1` — only Interested people for vacancy 1.

**6b. How to unzip ZIP (to read CVs)**
ZIP get one CV file per person, like `cv_7_Name.txt`. Na plain text, e go open for any phone.
- Android: tap ZIP for Telegram → Extract, or open am with Files app → long-press ZIP → Extract. CV files go show next to am. Tap any `.txt` to read am.
- iPhone: tap ZIP → Preview → Share → Save to Files → open Files, long-press ZIP → Uncompress.
- Windows: right-click ZIP → Extract All → Extract.
If you only need quick list, just open CSV — no need unzip.

**7. Start, stop, pause**
`/pause 1` — pause one vacancy. Others go still dey run.
`/resume 1` — start am again.
`/stop 1` — stop one vacancy.
`/pauseall` / `/resumeall` — pause / resume everything.
`/status` — see all vacancies and how many people each get.

**8. Quiet hours and school mode**
Bot no go disturb you for night. Default na 10pm to 7am.
`/school on` — busy mode, pause everything. `/school off` — back to normal.
If you dey school or you need break, use am. No wahala.

**9. Daily to-do**
Bot go send you to-do by itself every morning for 8am (unless school mode dey on).
Send `/todo` any time to see am again. E go show you:
New people to review, people you never text yet, follow-ups wey don due.

**10. If something look wrong**
Wrong vacancy? `/edit 1 pay_text=₦600,000`
Wrong person? `/block 5` hide am. `/unblock 5` bring am back.
Bot dey send too much? `/live 1 off` — e go stop live push for vacancy 1. You go still get everything with `/harvest`.
Still wrong? Send `/status` and tell me wetin you see.

You go see all commands when you type `/` for the bot. You no need memorize them.

You dey in control. Bot dey find. You dey decide. You dey text. I got you. 🤝
