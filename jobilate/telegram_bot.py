"""Telegram bot (python-telegram-bot v20+, Application-based, async).

HARD LIMIT — enforced here, non-negotiable:
The bot NEVER contacts candidates. It only ever sends to the ONE
recruiter chat (ADMIN_CHAT_ID). Every outbound send goes through
`guard_recipient`, which raises unless the target IS the recruiter.
There is no code path that sends to any other chat.
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime

from . import __version__
from .config import Config
from .csv_export import CSV_COLUMNS, build_digest, write_csv
from .dedup import dedup_candidates
from .harvest import harvest, harvest_counts
from .livepush import LivePushQueue, format_card, in_quiet_hours
from .matching import score_candidate
from .models import MARK_VALUES, Candidate, Vacancy, utcnow_iso
from .reminders import daily_todo, followups_due
from .sample_cvs import SAMPLE_CVS
from .store import Store
from .template import interview_checklist, render_template
from .vacancy_parser import parse_vacancy_text, vagueness

# Conversation states for /newvacancy wizard.
ROLE, LOCATION, PAY, REQ, EMPLOYER, DEADLINE, CONTACT, CONFIRM = range(8)

HELP_TEXT = """Jobilate Recruiter Bot — commands:

/start /help — welcome + this list
/newvacancy — add a vacancy (wizard, or paste the full text)
/vacancies — list vacancies
/vacancy <id> — show one vacancy
/edit <id> <field>=<value> — edit (e.g. /edit 1 pay_text=₦600,000)
/delete <id> — delete a vacancy
/start <id> /stop <id> /pause <id> /resume <id> — per vacancy
/startall /stopall /pauseall /resumeall — all vacancies
/status — all vacancy statuses + counts
/config — show config (no secrets) /set <key> <value> — change a setting
/contact — recruiter contact on file
/template <vacancy_id> [name] — show the fixed outreach text to copy
/limits — scrape limits + quiet hours
/live <id> on|off — live push per vacancy (global: /live off)
/candidates <vacancy_id> — list candidates for a vacancy
/candidate <candidate_id> — show one candidate
/search <text> — search candidates by name/title/skills
/feed — latest matches across vacancies
/stats [vacancy_id] — counts by tier + marks
/block <candidate_id> /unblock <candidate_id>
/shortlist <vacancy_id> — Interested candidates for a vacancy
/contacts — all candidate contacts (for your own outreach)
/export [vacancy_id] /exportcsv [vacancy_id] — CSV file
/backup — ZIP of DB + CSVs
/harvest [vacancy_id|unsent|unsent_employer|all] — digest + CSV
/dump [vacancy_id] — everything (digest + CSV)
/todo — daily to-do + follow-ups
/school on|off — busy mode (pause-all)
/demo — run a demo match against sample CVs (no scraping)

Marks (tap the buttons on a card, or type):
/mark <vacancy_id> <candidate_id> <Texted|Interested|No reply|Not fit|Sent to employer>

The bot NEVER contacts candidates. You text them yourself.
"""


def guard_recipient(chat_id, admin_chat_id) -> None:
    """HARD LIMIT guard: raise unless the target IS the recruiter chat.

    Every outbound Telegram send must call this first. Any attempt to
    send to any other chat raises PermissionError and nothing is sent.
    """
    if str(chat_id) != str(admin_chat_id):
        raise PermissionError(f"Refused: outbound sends are only allowed to the recruiter chat, not {chat_id!r}")


async def send_to_recruiter(context, chat_id, text: str, admin_chat_id: str, **kwargs):
    """The ONLY outbound-send helper. Guarded to the recruiter chat."""
    guard_recipient(chat_id, admin_chat_id)
    return await context.bot.send_message(chat_id=int(chat_id), text=text, **kwargs)


def format_vacancy(v: Vacancy) -> str:
    return (
        f"#{v.id} {v.title}\n"
        f"📍 {v.location} · {v.job_type} · Priority: {v.priority}\n"
        f"💰 {v.pay_text}\n"
        f"🏢 {v.employer or '—'} · Deadline: {v.deadline or '—'}\n"
        f"Status: {v.status} · Live: {'on' if v.live_push else 'off'}\n"
        f"Req: {v.requirements_text or '—'}"
    )


def format_candidate_row(link: dict, store: Store, vacancy_id: int) -> str:
    others = [o.label() for o in store.other_vacancies_for_candidate(link["candidate_id"], vacancy_id)]
    tag = f"\nAlso matches: {', '.join(others)}" if others else ""
    return (
        f"{link.get('tier', '')} · #{link.get('candidate_id')} {link.get('name', '')} — {link.get('ctitle', '')}\n"
        f"📞 {link.get('phone', '')} · 📍 {link.get('cloc', '')} · Mark: {link.get('mark') or '—'}\n"
        f"Why: {link.get('match_reason', '')}{tag}"
    )


def _vid(args: list[str]) -> int | None:
    try:
        return int(args[0]) if args else None
    except ValueError:
        return None


class JobilateBot:
    def __init__(self, config: Config, store: Store):
        self.config = config
        self.store = store
        self.live_queue = LivePushQueue(batch_minutes=config.live_batch_minutes, batch_size=config.live_batch_size)
        self.school_mode = False

    # ---- generic helpers ----
    def _admin(self, update) -> str:
        return self.config.admin_chat_id

    def _quiet_now(self) -> bool:
        return in_quiet_hours(datetime.now(), self.config.quiet_hours_start, self.config.quiet_hours_end)

    def _vacancy_or_reply(self, vid: int | None):
        if vid is None:
            return None, "Usage: give a vacancy id, e.g. /vacancy 1. See /vacancies."
        v = self.store.get_vacancy(vid)
        if not v:
            return None, f"No vacancy #{vid}. See /vacancies."
        return v, ""

    # ---- basic ----
    async def cmd_start(self, update, context):
        # /start <id> activates a vacancy; bare /start is the welcome.
        vid = _vid(context.args or [])
        if vid is not None:
            await update.message.reply_text(self._set_status(vid, "active"))
            return
        await update.message.reply_text("Welcome to Jobilate Recruiter Bot 🤝\n\nI find CVs on public Jiji pages and bring them to you. I never contact candidates — you text them yourself.\n\nSend /newvacancy to add a vacancy, or /help for all commands.")

    async def cmd_help(self, update, context):
        await update.message.reply_text(HELP_TEXT)

    async def cmd_status(self, update, context):
        vacs = self.store.list_vacancies()
        if not vacs:
            await update.message.reply_text("No vacancies yet. Send /newvacancy to add one.")
            return
        lines = ["📊 Status"]
        for v in vacs:
            st = self.store.stats_for_vacancy(v.id)
            lines.append(f"{v.label()} — {v.status}, live={'on' if v.live_push else 'off'}, {st['total']} cands ({st.get('Tier1', 0)} T1 / {st.get('Tier2', 0)} T2 / {st.get('Tier3', 0)} T3)")
        lines.append(f"\nSchool mode: {'ON (paused)' if self.school_mode else 'off'} · Quiet now: {'yes' if self._quiet_now() else 'no'}")
        await update.message.reply_text("\n".join(lines))

    async def cmd_config(self, update, context):
        c = self.config
        await update.message.reply_text(
            f"Config (no secrets shown):\nDATA_DIR={c.data_dir}\nQUIET_HOURS={c.quiet_hours_start:02d}:00–{c.quiet_hours_end:02d}:00\nSCRAPE_MIN_DELAY={c.scrape_min_delay_seconds}s\nCACHE_TTL={c.cache_ttl_minutes} min\nLIVE_BATCH={c.live_batch_minutes} min / {c.live_batch_size} new\nSchool mode: {'on' if self.school_mode else 'off'}\nVersion: {__version__}")

    async def cmd_set(self, update, context):
        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text("Usage: /set <key> <value>\nKeys: quiet_start, quiet_end, live_batch_minutes, live_batch_size, school")
            return
        key, val = args[0].lower(), args[1]
        try:
            if key == "quiet_start":
                self.config.quiet_hours_start = int(val)
            elif key == "quiet_end":
                self.config.quiet_hours_end = int(val)
            elif key == "live_batch_minutes":
                self.config.live_batch_minutes = int(val)
                self.live_queue.batch_minutes = int(val)
            elif key == "live_batch_size":
                self.config.live_batch_size = int(val)
                self.live_queue.batch_size = int(val)
            elif key == "school":
                self.school_mode = val.lower() in ("on", "1", "true", "yes")
            else:
                await update.message.reply_text(f"Unknown key: {key}")
                return
        except ValueError:
            await update.message.reply_text("Value must be a number for that key.")
            return
        await update.message.reply_text(f"Set {key} = {val}.")

    async def cmd_contact(self, update, context):
        await update.message.reply_text("Recruiter contact on file: see your vacancy /contact field per vacancy.\nUse /edit <id> contact=<value> to update it.\nThe bot never shares contacts anywhere except to you.")

    async def cmd_template(self, update, context):
        args = context.args or []
        v, err = self._vacancy_or_reply(_vid(args))
        if err:
            await update.message.reply_text(err)
            return
        name = args[1] if len(args) > 1 else ""
        txt = render_template({"title": v.title, "location": v.location, "pay_text": v.pay_text, "job_type": v.job_type, "requirements_text": v.requirements_text}, candidate_name=name)
        await update.message.reply_text("Copy this fixed text and send it yourself:\n\n" + txt)

    async def cmd_limits(self, update, context):
        await update.message.reply_text(
            f"Limits:\n• Jiji scrape: ≥{self.config.scrape_min_delay_seconds:g}s between page loads, cache {self.config.cache_ttl_minutes} min\n• Public pages only, no login\n• Quiet hours {self.config.quiet_hours_start:02d}:00–{self.config.quiet_hours_end:02d}:00 (no live pushes then)\n• Live push: Tier1 immediate, rest batched {self.config.live_batch_minutes} min / {self.config.live_batch_size} new\n• Bot NEVER contacts candidates.")

    async def cmd_school(self, update, context):
        arg = (context.args[0].lower() if context.args else "")
        if arg in ("on", "off"):
            self.school_mode = arg == "on"
            for v in self.store.list_vacancies():
                self.store.update_vacancy(v.id, status="paused" if self.school_mode else ("active" if v.status == "paused" else v.status), school_mode=self.school_mode)
            await update.message.reply_text(f"School/busy mode {'ON — all vacancies paused' if self.school_mode else 'OFF — vacancies restored to active where they were paused'}.")
        else:
            await update.message.reply_text(f"School mode is {'ON' if self.school_mode else 'OFF'}. Use /school on or /school off.")

    # ---- vacancies ----
    async def cmd_vacancies(self, update, context):
        vacs = self.store.list_vacancies()
        if not vacs:
            await update.message.reply_text("No vacancies yet. Send /newvacancy to add one.")
            return
        await update.message.reply_text("\n\n".join(format_vacancy(v) for v in vacs))

    async def cmd_vacancy(self, update, context):
        v, err = self._vacancy_or_reply(_vid(context.args or []))
        if err:
            await update.message.reply_text(err)
            return
        st = self.store.stats_for_vacancy(v.id)
        await update.message.reply_text(format_vacancy(v) + f"\nCandidates: {st['total']} (T1 {st.get('Tier1', 0)} / T2 {st.get('Tier2', 0)} / T3 {st.get('Tier3', 0)})")

    async def cmd_edit(self, update, context):
        args = context.args or []
        if len(args) < 2 or "=" not in " ".join(args[1:]):
            await update.message.reply_text("Usage: /edit <id> field=value [field=value ...]\nFields: title, location, pay_text, job_type, requirements_text, employer, deadline, contact, priority, status")
            return
        v, err = self._vacancy_or_reply(_vid(args))
        if err:
            await update.message.reply_text(err)
            return
        fields: dict = {}
        for part in args[1:]:
            if "=" in part:
                k, val = part.split("=", 1)
                fields[k.strip()] = val.strip()
        ok = self.store.update_vacancy(v.id, **fields)
        await update.message.reply_text(f"Updated #{v.id}." if ok else "Nothing updated — check field names.")

    async def cmd_delete(self, update, context):
        v, err = self._vacancy_or_reply(_vid(context.args or []))
        if err:
            await update.message.reply_text(err)
            return
        self.store.delete_vacancy(v.id)
        await update.message.reply_text(f"Deleted #{v.id} {v.title} and its links.")

    def _set_status(self, vid: int | None, status: str) -> str:
        v, err = self._vacancy_or_reply(vid)
        if err:
            return err
        self.store.update_vacancy(v.id, status=status)
        return f"{v.label()} → {status}."

    async def cmd_start(self, update, context):
        await update.message.reply_text(self._set_status(_vid(context.args or []), "active"))

    async def cmd_stop(self, update, context):
        await update.message.reply_text(self._set_status(_vid(context.args or []), "stopped"))

    async def cmd_pause(self, update, context):
        await update.message.reply_text(self._set_status(_vid(context.args or []), "paused"))

    async def cmd_resume(self, update, context):
        await update.message.reply_text(self._set_status(_vid(context.args or []), "active"))

    async def _bulk(self, status: str) -> str:
        vacs = self.store.list_vacancies()
        for v in vacs:
            self.store.update_vacancy(v.id, status=status)
        return f"{len(vacs)} vacanc(ies) → {status}."

    async def cmd_startall(self, update, context):
        await update.message.reply_text(self._bulk("active"))

    async def cmd_stopall(self, update, context):
        await update.message.reply_text(self._bulk("stopped"))

    async def cmd_pauseall(self, update, context):
        await update.message.reply_text(self._bulk("paused"))

    async def cmd_resumeall(self, update, context):
        await update.message.reply_text(self._bulk("active"))

    async def cmd_live(self, update, context):
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /live <vacancy_id> on|off  or  /live off (global harvest-only)")
            return
        if len(args) == 1 and args[0].lower() in ("on", "off"):
            on = args[0].lower() == "on"
            for v in self.store.list_vacancies():
                self.store.update_vacancy(v.id, live_push=on)
            await update.message.reply_text(f"Global live push {'ON' if on else 'OFF (harvest-only)'} for all vacancies.")
            return
        v, err = self._vacancy_or_reply(_vid(args))
        if err:
            await update.message.reply_text(err)
            return
        if len(args) < 2:
            await update.message.reply_text(f"Live push for {v.label()} is {'on' if v.live_push else 'off'}. Use /live {v.id} on|off.")
            return
        on = args[1].lower() in ("on", "1", "true", "yes")
        self.store.update_vacancy(v.id, live_push=on)
        await update.message.reply_text(f"Live push for {v.label()} → {'on' if on else 'off'}.")

    # ---- candidates ----
    async def cmd_candidates(self, update, context):
        v, err = self._vacancy_or_reply(_vid(context.args or []))
        if err:
            await update.message.reply_text(err)
            return
        links = self.store.links_for_vacancy(v.id)
        if not links:
            await update.message.reply_text(f"No candidates yet for {v.label()}. Run a scrape / demo first.")
            return
        await update.message.reply_text("\n\n".join(format_candidate_row(ln, self.store, v.id) for ln in links[:20]))

    async def cmd_candidate(self, update, context):
        try:
            cid = int((context.args or [""])[0])
        except ValueError:
            await update.message.reply_text("Usage: /candidate <candidate_id>")
            return
        c = self.store.get_candidate(cid)
        if not c:
            await update.message.reply_text(f"No candidate #{cid}.")
            return
        await update.message.reply_text(
            f"#{c.id} {c.name}\n📞 {c.phone} · 📍 {c.location}\n{c.title}\n🎓 {c.highest_qualification or c.education or '—'}\n💼 {c.experience_years if c.experience_years is not None else '—'}y · 💰 {c.expected_salary or '—'}\nSkills: {c.skills or '—'}\nCV: {c.cv_url or '—'}\nBlocked: {'yes' if c.blocked else 'no'}")

    async def cmd_search(self, update, context):
        q = " ".join(context.args or []).lower()
        if not q:
            await update.message.reply_text("Usage: /search <text>")
            return
        hits = [ln for ln in self.store.all_links() if q in f"{ln.get('name','')} {ln.get('ctitle','')} {ln.get('cloc','')}".lower()]
        if not hits:
            await update.message.reply_text(f"No candidates matching '{q}'.")
            return
        await update.message.reply_text("\n\n".join(format_candidate_row(ln, self.store, ln["vacancy_id"]) for ln in hits[:15]))

    async def cmd_feed(self, update, context):
        links = self.store.all_links()[-15:]
        if not links:
            await update.message.reply_text("Feed is empty — no matches yet.")
            return
        await update.message.reply_text("\n\n".join(format_candidate_row(ln, self.store, ln["vacancy_id"]) for ln in links))

    async def cmd_stats(self, update, context):
        vid = _vid(context.args or [])
        if vid is not None:
            v, err = self._vacancy_or_reply(vid)
            if err:
                await update.message.reply_text(err)
                return
            st = self.store.stats_for_vacancy(v.id)
            lines = [f"Stats — {v.label()}", f"Total: {st['total']} · Tier1 {st.get('Tier1',0)} · Tier2 {st.get('Tier2',0)} · Tier3 {st.get('Tier3',0)}"]
            for k in sorted(st):
                if k.startswith("mark:"):
                    lines.append(f"{k[5:]}: {st[k]}")
            await update.message.reply_text("\n".join(lines))
            return
        lines = ["Stats — all vacancies"]
        for v in self.store.list_vacancies():
            st = self.store.stats_for_vacancy(v.id)
            lines.append(f"{v.label()}: {st['total']} (T1 {st.get('Tier1',0)} / T2 {st.get('Tier2',0)} / T3 {st.get('Tier3',0)})")
        await update.message.reply_text("\n".join(lines))

    async def cmd_block(self, update, context):
        try:
            cid = int((context.args or [""])[0])
        except ValueError:
            await update.message.reply_text("Usage: /block <candidate_id>")
            return
        ok = self.store.set_blocked(cid, True)
        await update.message.reply_text(f"Candidate #{cid} blocked." if ok else f"No candidate #{cid}.")

    async def cmd_unblock(self, update, context):
        try:
            cid = int((context.args or [""])[0])
        except ValueError:
            await update.message.reply_text("Usage: /unblock <candidate_id>")
            return
        ok = self.store.set_blocked(cid, False)
        await update.message.reply_text(f"Candidate #{cid} unblocked." if ok else f"No candidate #{cid}.")

    async def cmd_shortlist(self, update, context):
        v, err = self._vacancy_or_reply(_vid(context.args or []))
        if err:
            await update.message.reply_text(err)
            return
        links = [ln for ln in self.store.links_for_vacancy(v.id) if ln.get("mark") == "Interested"]
        if not links:
            await update.message.reply_text(f"No Interested candidates yet for {v.label()}.")
            return
        await update.message.reply_text("⭐ Shortlist — " + v.label() + "\n\n" + "\n\n".join(format_candidate_row(ln, self.store, v.id) for ln in links))

    async def cmd_contacts(self, update, context):
        links = self.store.all_links()
        if not links:
            await update.message.reply_text("No contacts yet.")
            return
        seen: dict[str, dict] = {}
        for ln in links:
            seen.setdefault(ln.get("phone", ""), ln)
        lines = ["📇 Contacts (for YOUR outreach only — bot never contacts them):"]
        for ln in seen.values():
            lines.append(f"{ln.get('name','')} — {ln.get('phone','')} — {ln.get('ctitle','')}")
        await update.message.reply_text("\n".join(lines))

    async def cmd_mark(self, update, context):
        args = context.args or []
        if len(args) < 3:
            await update.message.reply_text("Usage: /mark <vacancy_id> <candidate_id> <Texted|Interested|No reply|Not fit|Sent to employer>")
            return
        try:
            vid, cid = int(args[0]), int(args[1])
        except ValueError:
            await update.message.reply_text("Vacancy and candidate ids must be numbers.")
            return
        mark = " ".join(args[2:])
        # Normalise case: "no reply" -> "No reply", etc.
        for m in MARK_VALUES:
            if m.lower() == mark.lower():
                mark = m
                break
        if mark not in MARK_VALUES:
            await update.message.reply_text(f"Unknown mark. Use one of: {', '.join(MARK_VALUES)}")
            return
        ok = self.store.set_mark(vid, cid, mark)
        await update.message.reply_text(f"Marked candidate #{cid} as '{mark}' for vacancy #{vid}." if ok else "No such vacancy/candidate link. Check /candidates <vacancy_id>.")

    async def cmd_checklist(self, update, context):
        v, err = self._vacancy_or_reply(_vid(context.args or []))
        if err:
            await update.message.reply_text(err)
            return
        await update.message.reply_text(interview_checklist({"title": v.title, "requirements_text": v.requirements_text}))

    # ---- export / harvest / backup ----
    async def _send_csv(self, update, links: list[dict], vacancy_label: str, filename: str):
        os.makedirs(self.config.data_dir, exist_ok=True)
        path = os.path.join(self.config.data_dir, filename)
        write_csv(path, links, vacancy_label)
        guard_recipient(update.effective_chat.id, self.config.admin_chat_id)
        with open(path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename, caption=f"CSV — {vacancy_label} ({len(links)} rows)")

    async def cmd_export(self, update, context):
        await self._do_export(update, context, "export")

    async def cmd_exportcsv(self, update, context):
        await self._do_export(update, context, "exportcsv")

    async def _do_export(self, update, context, _name: str):
        vid = _vid(context.args or [])
        if vid is not None:
            v, err = self._vacancy_or_reply(vid)
            if err:
                await update.message.reply_text(err)
                return
            links = self.store.links_for_vacancy(v.id)
            await self._send_csv(update, links, v.label(), f"vacancy_{v.id}.csv")
        else:
            await self._send_csv(update, self.store.all_links(), "All vacancies", "all_candidates.csv")

    async def cmd_harvest(self, update, context):
        args = [a.lower() for a in (context.args or [])]
        mode, vid = "incremental", None
        if args:
            if args[0] == "unsent":
                mode = "unsent"
            elif args[0] in ("unsent_employer", "unsent-employer"):
                mode = "unsent_employer"
            elif args[0] == "all":
                mode = "all"
            else:
                try:
                    vid = int(args[0])
                except ValueError:
                    await update.message.reply_text("Usage: /harvest [vacancy_id|unsent|unsent_employer|all]")
                    return
        links, digest = harvest(self.store, vid, mode)
        await update.message.reply_text(digest)
        if links:
            label = self.store.get_vacancy(vid).label() if vid else "All vacancies"
            await self._send_csv(update, links, label, f"harvest_{vid or 'all'}.csv")

    async def cmd_dump(self, update, context):
        vid = _vid(context.args or [])
        links, digest = harvest(self.store, vid, "all")
        await update.message.reply_text(digest)
        if links:
            label = self.store.get_vacancy(vid).label() if vid else "All vacancies"
            await self._send_csv(update, links, label, f"dump_{vid or 'all'}.csv")

    async def cmd_backup(self, update, context):
        os.makedirs(self.config.data_dir, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(self.store.path):
                zf.write(self.store.path, os.path.basename(self.store.path))
            for fn in os.listdir(self.config.data_dir):
                if fn.endswith(".csv"):
                    zf.write(os.path.join(self.config.data_dir, fn), fn)
        buf.seek(0)
        guard_recipient(update.effective_chat.id, self.config.admin_chat_id)
        await update.message.reply_document(document=buf, filename="jobilate_backup.zip", caption="Backup: DB + CSVs (contacts only to you).")

    async def cmd_todo(self, update, context):
        due = followups_due(self.store)
        lines = [daily_todo(self.store)]
        if due:
            lines.append("\nFollow-ups due:")
            for ln in due[:10]:
                lines.append(f"• #{ln['candidate_id']} {ln.get('name','')} — texted {ln.get('marked_at','')[:10]}")
        await update.message.reply_text("\n".join(lines))

    async def cmd_demo(self, update, context):
        """Demo match run against bundled SAMPLE CVs (no scraping)."""
        vid = _vid(context.args or [])
        v, err = self._vacancy_or_reply(vid)
        if err:
            vacs = self.store.list_vacancies()
            if not vacs:
                await update.message.reply_text("No vacancy yet. Add one with /newvacancy first, then /demo <id>.")
                return
            v = vacs[0]
        vac = {"title": v.title, "location": v.location, "pay_min": v.pay_min, "requirements_text": v.requirements_text, "education_required": v.education_required, "min_years": v.min_years}
        added = []
        for cv in dedup_candidates([dict(c) for c in SAMPLE_CVS]):
            score, tier, reason = score_candidate(vac, cv)
            cid = self.store.add_or_get_candidate(Candidate(**{k: cv.get(k) for k in ("name", "phone", "title", "job_type", "employment_status", "education", "highest_qualification", "skills", "languages", "certifications", "experience_text", "experience_years", "expected_salary", "expected_salary_min", "location", "cv_url", "source")}))
            self.store.link_candidate(v.id, cid, score, tier, reason)
            added.append((cv, score, tier, reason))
        lines = [f"Demo run for {v.label()} — {len(added)} sample CVs scored:"]
        for cv, score, tier, reason in sorted(added, key=lambda x: -x[1]):
            lines.append(f"\n{tier} ({score:.0f}) {cv['name']} — {cv['title']}\nWhy: {reason}")
        await update.message.reply_text("\n".join(lines))

    # ---- /newvacancy wizard ----
    async def newvacancy_entry(self, update, context):
        text = (update.message.text or "").strip()
        # Pasted full vacancy after the command: parse immediately.
        pasted = text[len("/newvacancy"):].strip()
        if pasted:
            parsed = parse_vacancy_text(pasted)
            vague = vagueness(parsed)
            if vague == "too_vague":
                await update.message.reply_text("That looks too vague to scrape. Please tell me in one message: what role, where, and what qualifications? (e.g. 'Sales Supervisor, Lagos, B.Tech + 5 years vet drug sales')")
                return ROLE
            context.user_data["vacancy"] = parsed
            context.user_data["vacancy"]["raw_text"] = pasted
            await update.message.reply_text(f"I read this as:\n{self._draft_text(parsed)}\n\nReply YES to save it, or NO to start the step-by-step wizard.")
            return CONFIRM
        context.user_data["vacancy"] = {}
        await update.message.reply_text("Let's add a vacancy.\n\nStep 1 — What is the role? (e.g. Sales Supervisor)")
        return ROLE

    def _draft_text(self, d: dict) -> str:
        return (f"Role: {d.get('title','')}\nLocation: {d.get('location','')}\nPay: {d.get('pay_text','')}\n"
                f"Type: {d.get('job_type','Full-Time')}\nRequirements: {d.get('requirements_text','')}\n"
                f"Employer: {d.get('employer','')}\nDeadline: {d.get('deadline','')}")

    async def _wizard_step(self, update, context, key: str, next_state: int, prompt: str):
        context.user_data.setdefault("vacancy", {})[key] = (update.message.text or "").strip()
        await update.message.reply_text(prompt)
        return next_state

    async def newvacancy_role(self, update, context):
        return await self._wizard_step(update, context, "title", LOCATION, "Step 2 — Location? (e.g. Lagos State)")

    async def newvacancy_location(self, update, context):
        return await self._wizard_step(update, context, "location", PAY, "Step 3 — Pay? (e.g. ₦500,000+/month, or 'not stated')")

    async def newvacancy_pay(self, update, context):
        from .vacancy_parser import parse_pay
        raw = (update.message.text or "").strip()
        context.user_data.setdefault("vacancy", {})["pay_text"] = raw
        _, pay_min = parse_pay(raw)
        context.user_data["vacancy"]["pay_min"] = pay_min
        await update.message.reply_text("Step 4 — Requirements? (education, years of experience, skills — one message)")
        return REQ

    async def newvacancy_req(self, update, context):
        from .vacancy_parser import extract_education, extract_years
        req = (update.message.text or "").strip()
        d = context.user_data.setdefault("vacancy", {})
        d["requirements_text"] = req
        d["education_required"] = extract_education(req)
        d["min_years"] = extract_years(req)
        await update.message.reply_text("Step 5 — Employer / company name? (or 'not stated')")
        return EMPLOYER

    async def newvacancy_employer(self, update, context):
        return await self._wizard_step(update, context, "employer", DEADLINE, "Step 6 — Deadline? (e.g. 2026-10-31, or 'none')")

    async def newvacancy_deadline(self, update, context):
        return await self._wizard_step(update, context, "deadline", CONTACT, "Step 7 — Contact for this vacancy? (who should candidates reach — leave blank if same as usual)")

    async def newvacancy_contact(self, update, context):
        context.user_data.setdefault("vacancy", {})["contact"] = (update.message.text or "").strip()
        d = context.user_data["vacancy"]
        d.setdefault("job_type", "Full-Time")
        d.setdefault("priority", "Normal")
        await update.message.reply_text(f"Please check:\n{self._draft_text(d)}\n\nReply YES to save, or NO to cancel.")
        return CONFIRM

    async def newvacancy_confirm(self, update, context):
        ans = (update.message.text or "").strip().lower()
        if ans not in ("yes", "y", "ok", "confirm", "save"):
            context.user_data.pop("vacancy", None)
            await update.message.reply_text("Cancelled. Send /newvacancy to try again.")
            from telegram.ext import ConversationHandler
            return ConversationHandler.END
        d = context.user_data.get("vacancy", {})
        v = Vacancy(title=d.get("title", ""), location=d.get("location", ""), pay_text=d.get("pay_text", ""), pay_min=d.get("pay_min"), job_type=d.get("job_type", "Full-Time"), requirements_text=d.get("requirements_text", ""), education_required=d.get("education_required", ""), min_years=d.get("min_years"), employer=d.get("employer", ""), deadline=d.get("deadline", ""), contact=d.get("contact", ""), priority=d.get("priority", "Normal"), status="active", raw_text=d.get("raw_text", ""))
        vid = self.store.add_vacancy(v)
        context.user_data.pop("vacancy", None)
        await update.message.reply_text(f"Saved as vacancy #{vid} and set ACTIVE.\n\n{format_vacancy(self.store.get_vacancy(vid))}\n\nNext: /demo {vid} to try a demo match, or wait for scraping to find CVs.")
        from telegram.ext import ConversationHandler
        return ConversationHandler.END

    async def newvacancy_cancel(self, update, context):
        context.user_data.pop("vacancy", None)
        await update.message.reply_text("Cancelled.")
        from telegram.ext import ConversationHandler
        return ConversationHandler.END

    # ---- callback buttons (one-tap marks) ----
    async def on_callback(self, update, context):
        q = update.callback_query
        await q.answer()
        data = (q.data or "")
        parts = data.split(":")
        if len(parts) == 4 and parts[0] == "mark":
            try:
                vid, cid = int(parts[1]), int(parts[2])
            except ValueError:
                await q.edit_message_text("Bad button data.")
                return
            mark = parts[3]
            if mark not in MARK_VALUES:
                await q.edit_message_text("Unknown mark.")
                return
            ok = self.store.set_mark(vid, cid, mark)
            await q.edit_message_text(f"Marked candidate #{cid} as '{mark}' for vacancy #{vid}." if ok else "Link not found.")
            return
        await q.edit_message_text("Unknown button.")

    def build_application(self):
        from telegram import BotCommand, Update
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

        async def post_init(app):
            # Commands menu she sees when she types "/" or taps the menu button.
            # Kept to the 16 she actually needs — the rest still work by typing.
            await app.bot.set_my_commands([
                BotCommand("start", "Start the bot"),
                BotCommand("help", "Show all commands"),
                BotCommand("newvacancy", "Add a new vacancy"),
                BotCommand("vacancies", "List your vacancies"),
                BotCommand("candidates", "List candidates"),
                BotCommand("harvest", "Get new candidates + CSV"),
                BotCommand("dump", "Get everything + CSV"),
                BotCommand("todo", "Today's to-do + follow-ups"),
                BotCommand("export", "Get CSV file"),
                BotCommand("template", "Show message to copy"),
                BotCommand("mark", "Mark a candidate"),
                BotCommand("pause", "Pause a vacancy"),
                BotCommand("resume", "Resume a vacancy"),
                BotCommand("stop", "Stop a vacancy"),
                BotCommand("status", "See bot status"),
                BotCommand("school", "School / busy mode"),
            ])

        app = ApplicationBuilder().token(self.config.bot_token).post_init(post_init).build()
        b = self
        conv = ConversationHandler(
            entry_points=[CommandHandler("newvacancy", b.newvacancy_entry)],
            states={
                ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_role)],
                LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_location)],
                PAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_pay)],
                REQ: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_req)],
                EMPLOYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_employer)],
                DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_deadline)],
                CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_contact)],
                CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, b.newvacancy_confirm)],
            },
            fallbacks=[CommandHandler("cancel", b.newvacancy_cancel)],
        )
        app.add_handler(conv)
        simple = {
            "start": b.cmd_start, "help": b.cmd_help, "vacancies": b.cmd_vacancies,
            "vacancy": b.cmd_vacancy, "edit": b.cmd_edit, "delete": b.cmd_delete,
            "start_v": b.cmd_start, "stop": b.cmd_stop, "pause": b.cmd_pause,
            "resume": b.cmd_resume, "startall": b.cmd_startall, "stopall": b.cmd_stopall,
            "pauseall": b.cmd_pauseall, "resumeall": b.cmd_resumeall, "status": b.cmd_status,
            "config": b.cmd_config, "set": b.cmd_set, "contact": b.cmd_contact,
            "template": b.cmd_template, "limits": b.cmd_limits, "live": b.cmd_live,
            "candidates": b.cmd_candidates, "candidate": b.cmd_candidate, "search": b.cmd_search,
            "feed": b.cmd_feed, "stats": b.cmd_stats, "block": b.cmd_block,
            "unblock": b.cmd_unblock, "shortlist": b.cmd_shortlist, "contacts": b.cmd_contacts,
            "export": b.cmd_export, "exportcsv": b.cmd_exportcsv, "backup": b.cmd_backup,
            "harvest": b.cmd_harvest, "dump": b.cmd_dump, "todo": b.cmd_todo,
            "school": b.cmd_school, "demo": b.cmd_demo, "mark": b.cmd_mark,
            "checklist": b.cmd_checklist,
        }
        # /start is both a vacancy command and the welcome command; the
        # welcome handler wins for bare /start, vacancy start uses /start <id>.
        app.add_handler(CommandHandler("start", b.cmd_start))
        for name, fn in simple.items():
            if name in ("start", "start_v"):
                continue
            app.add_handler(CommandHandler(name, fn))
        # /start <id> activates a vacancy: handled inside cmd_start via args.
        app.add_handler(CallbackQueryHandler(b.on_callback))
        return app
