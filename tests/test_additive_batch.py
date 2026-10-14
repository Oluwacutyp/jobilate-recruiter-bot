"""ADDITIVE batch tests (2026-10-14): /start fix, aliases, parser for her
paste, short /help, YES/NO buttons, just-paste, /howto, /keyboard,
reply keyboard, auto-scrape survival. Nothing here removes old behaviour.
"""
import asyncio
import os
import sys
import types
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# --- Minimal telegram stub (used only if python-telegram-bot is absent).
# The bot imports telegram lazily inside functions; the stub lets these
# tests exercise button/keyboard code paths without a live install.
try:
    import telegram  # noqa: F401
except ImportError:
    _tg = types.ModuleType("telegram")

    class _Btn:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    class _Markup:
        def __init__(self, inline_keyboard=None, keyboard=None, **kw):
            self.inline_keyboard = inline_keyboard
            self.keyboard = keyboard
            self.kwargs = kw

    class _KB:
        def __init__(self, text):
            self.text = text

    class _Remove:
        pass

    _tg.InlineKeyboardButton = _Btn
    _tg.InlineKeyboardMarkup = _Markup
    _tg.KeyboardButton = _KB
    _tg.ReplyKeyboardMarkup = _Markup
    _tg.ReplyKeyboardRemove = _Remove
    sys.modules["telegram"] = _tg
    _ext = types.ModuleType("telegram.ext")

    class _Conv:
        END = -1

    _ext.ConversationHandler = _Conv
    _ext.ApplicationBuilder = object
    _ext.CallbackQueryHandler = object
    _ext.CommandHandler = object
    _ext.MessageHandler = object
    _ext.filters = SimpleNamespace(TEXT=object(), COMMAND=object())
    sys.modules["telegram.ext"] = _ext

from jobilate.autoscrape import (
    REPLY_BUTTON_ACTIONS,
    REPLY_KEYBOARD_LAYOUT,
    SHORT_HELP_TEXT,
    build_reply_keyboard,
    looks_like_vacancy,
    scrape_all_active,
    scrape_one_vacancy,
    should_send_todo,
)
from jobilate.config import Config
from jobilate.models import Vacancy
from jobilate.store import Store
from jobilate.telegram_bot import HELP_TEXT, JobilateBot
from jobilate.vacancy_parser import parse_vacancy_text

HER_PASTE = """JOB VACANCY: SALES SUPERVISOR

Industry: Agro-Pharmaceuticals
Location: Lagos State
Salary: ₦500,000+monthly
Employment Type: Full-Time

Requirements:

* Education (Mandatory): B.Tech, B.Agric, HND in Animal Production and Health, or B.Sc. in Animal Health Technology.
* Minimum of 5 years’ verifiable experience in agro-pharmaceutical sales, particularly veterinary drugs.
* Strong industry connections with feed millers, commercial farms, agro-dealers, and distributors.
* Proven sales, business development, and team leadership skills.
* Willingness to travel when required.

Key Responsibilities:

* Drive sales and develop new markets.
* Manage key clients and maintain business relationships.
* Supervise sales representatives and achieve sales targets.
* Monitor market trends and prepare sales reports."""


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class _FakeMessage:
    def __init__(self, text="", chat_id="123"):
        self.text = text
        self.chat = SimpleNamespace(id=chat_id)
        self.replies = []
        self.documents = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return None

    async def reply_document(self, **kwargs):
        self.documents.append(kwargs)
        return None


class _FakeUpdate:
    def __init__(self, text="", chat_id="123"):
        self.message = _FakeMessage(text, chat_id)
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.callback_query = None


class _FakeContext:
    def __init__(self, args=None, user_data=None):
        self.args = args if args is not None else []
        self.user_data = user_data if user_data is not None else {}
        self.bot = SimpleNamespace()


def _bot(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    return JobilateBot(Config(bot_token="x", admin_chat_id="123"), store), store


# ---- 1. /start fix: single def, bare /start = welcome ----
def test_start_defined_once():
    src = open(os.path.join(os.path.dirname(__file__), "..", "jobilate", "telegram_bot.py"), encoding="utf-8").read()
    assert src.count("async def cmd_start(") == 1


def test_bare_start_is_welcome(tmp_path):
    bot, _ = _bot(tmp_path)
    upd, ctx = _FakeUpdate("/start"), _FakeContext()
    _run(bot.cmd_start(upd, ctx))
    assert upd.message.replies, "bare /start sent nothing"
    assert "Welcome" in upd.message.replies[0][0]
    assert "Usage: give a vacancy id" not in upd.message.replies[0][0]


# ---- 4. Parser for her exact paste ----
def test_parser_her_exact_paste():
    p = parse_vacancy_text(HER_PASTE)
    assert p["title"] == "Sales Supervisor"
    assert "Lagos" in p["location"]
    assert p["pay_min"] == 500000
    assert p["min_years"] == 5
    for kw in ("b.tech", "b.agric", "hnd", "b.sc"):
        assert kw in p["education_required"]
    assert p["job_type"] == "Full-Time"
    assert "Agro-Pharmaceuticals" in p["employer"]
    assert "Drive sales" in p["requirements_text"]


# ---- 4. Aliases registered + reentry ----
def test_aliases_registered():
    src = open(os.path.join(os.path.dirname(__file__), "..", "jobilate", "telegram_bot.py"), encoding="utf-8").read()
    assert 'CommandHandler("newvacancies"' in src
    assert 'CommandHandler("addvacancy"' in src
    assert "allow_reentry=True" in src


# ---- 6. YES/NO buttons on draft ----
def test_draft_has_yes_no_buttons(tmp_path):
    bot, _ = _bot(tmp_path)
    upd, ctx = _FakeUpdate("/newvacancy " + HER_PASTE), _FakeContext()
    _run(bot.newvacancy_entry(upd, ctx))
    assert upd.message.replies
    kwargs = upd.message.replies[0][1]
    assert "reply_markup" in kwargs and kwargs["reply_markup"] is not None


# ---- 7. Short /help vs /help all ----
def test_help_short_vs_all(tmp_path):
    bot, _ = _bot(tmp_path)
    upd, ctx = _FakeUpdate("/help"), _FakeContext()
    _run(bot.cmd_help(upd, ctx))
    assert "quick start" in upd.message.replies[0][0].lower()
    assert HELP_TEXT not in upd.message.replies[0][0]  # short, not full
    upd2, ctx2 = _FakeUpdate("/help all"), _FakeContext(args=["all"])
    _run(bot.cmd_help(upd2, ctx2))
    assert upd2.message.replies[0][0] == HELP_TEXT  # full text unchanged


# ---- 8. Just-paste detection ----
def test_looks_like_vacancy():
    assert looks_like_vacancy(HER_PASTE) is True
    assert looks_like_vacancy("hi") is False
    assert looks_like_vacancy("ok") is False


def test_plaintext_vacancy_prompts_and_hi_ignored(tmp_path):
    bot, _ = _bot(tmp_path)
    upd, ctx = _FakeUpdate(HER_PASTE), _FakeContext()
    _run(bot.handle_plaintext(upd, ctx))
    assert any("Is this a new vacancy?" in t for t, _ in upd.message.replies)
    assert ctx.user_data.get("paste_pending_text") == HER_PASTE
    upd2, ctx2 = _FakeUpdate("hi"), _FakeContext()
    _run(bot.handle_plaintext(upd2, ctx2))
    assert upd2.message.replies == []


# ---- 9. /howto ----
def test_howto_sends_guide(tmp_path):
    bot, _ = _bot(tmp_path)
    upd, ctx = _FakeUpdate("/howto"), _FakeContext()
    _run(bot.cmd_howto(upd, ctx))
    joined = "\n".join(t for t, _ in upd.message.replies)
    assert "How to use am" in joined or "how to use" in joined.lower()


# ---- Reply keyboard (additional requirement) ----
def test_reply_keyboard_layout():
    flat = [b for row in REPLY_KEYBOARD_LAYOUT for b in row]
    assert len(flat) == 6
    for label in ("➕ Add Vacancy", "📋 My Vacancies", "📥 Harvest", "📝 To-Do", "📊 Status", "❓ How to use"):
        assert label in flat
        assert label in REPLY_BUTTON_ACTIONS
    assert REPLY_BUTTON_ACTIONS["➕ Add Vacancy"] == "newvacancy"
    assert REPLY_BUTTON_ACTIONS["📥 Harvest"] == "harvest"
    assert REPLY_BUTTON_ACTIONS["❓ How to use"] == "howto"
    kb = build_reply_keyboard()
    assert kb is not None


def test_keyboard_on_off(tmp_path):
    bot, _ = _bot(tmp_path)
    upd, ctx = _FakeUpdate("/keyboard off"), _FakeContext(args=["off"])
    _run(bot.cmd_keyboard(upd, ctx))
    assert "hidden" in upd.message.replies[0][0].lower()
    upd2, ctx2 = _FakeUpdate("/keyboard on"), _FakeContext(args=["on"])
    _run(bot.cmd_keyboard(upd2, ctx2))
    assert "on" in upd2.message.replies[0][0].lower()


def test_reply_button_harvest_dispatch(tmp_path):
    bot, store = _bot(tmp_path)
    upd, ctx = _FakeUpdate("📥 Harvest"), _FakeContext()
    _run(bot.handle_plaintext(upd, ctx))
    assert upd.message.replies  # harvest ran (empty store -> "No candidates" digest)


# ---- 3. Auto-scrape survives Jiji errors ----
class _FailingScraper:
    def __init__(self, *args, **kwargs):
        pass

    def search_url(self, q):
        return "https://example.test/search"

    def fetch(self, url):
        from jobilate.scraper import JijiScrapeError

        raise JijiScrapeError("blocked")

    def parse_cv_list_html(self, html):
        return []

    def parse_cv_detail_html(self, html, url=""):
        return {}


class _CannedScraper:
    def __init__(self, *args, **kwargs):
        pass

    def search_url(self, q):
        return "https://example.test/search"

    def fetch(self, url):
        return "html"

    def parse_cv_list_html(self, html):
        return [{"title": "Sales Rep", "cv_url": "https://example.test/cv-1"}]

    def parse_cv_detail_html(self, html, url=""):
        return {
            "name": "Test Person", "phone": "+0000000009",
            "title": "Sales Representative — Vet Products",
            "job_type": "Full-Time", "employment_status": "Employed",
            "education": "B.Tech Animal Production", "highest_qualification": "B.Tech",
            "skills": "vet drug sales", "languages": "English",
            "certifications": "", "experience_text": "6 years agro-pharma sales",
            "experience_years": 6.0, "expected_salary": "₦400,000",
            "expected_salary_min": 400000, "location": "Lagos State",
            "cv_url": url, "source": "jiji",
        }


def test_scrape_survives_block(tmp_path):
    _, store = _bot(tmp_path)
    vid = store.add_vacancy(Vacancy(title="Sales Supervisor", location="Lagos State", status="active"))
    v = store.get_vacancy(vid)
    links, err = scrape_one_vacancy(store, v, _FailingScraper())
    assert links == [] and err
    per, errors = scrape_all_active(store, _FailingScraper())
    assert per == {} and errors


def test_scrape_canned_finds_match(tmp_path):
    _, store = _bot(tmp_path)
    vid = store.add_vacancy(Vacancy(
        title="Sales Supervisor", location="Lagos State",
        requirements_text="B.Tech 6 years agro-pharma sales",
        education_required="b.tech", min_years=5, status="active"))
    v = store.get_vacancy(vid)
    links, err = scrape_one_vacancy(store, v, _CannedScraper())
    assert err is None
    assert len(links) == 1
    assert links[0].get("tier") in ("Tier1", "Tier2", "Tier3")


def test_scheduled_tasks_survive_block(tmp_path, monkeypatch):
    import jobilate.scraper as scraper_mod

    bot, store = _bot(tmp_path)
    store.add_vacancy(Vacancy(title="Sales Supervisor", location="Lagos State", status="active"))
    monkeypatch.setattr(scraper_mod, "JijiScraper", _FailingScraper)

    sent = []

    class _FakeBot:
        async def send_message(self, chat_id=None, text=None, **kw):
            sent.append(text)

        async def send_document(self, **kw):
            sent.append("doc")

    ctx = SimpleNamespace(bot=_FakeBot())
    report = _run(bot.run_scheduled_tasks(ctx))
    assert "scraped" in report


def test_should_send_todo():
    from datetime import datetime as _dt

    assert should_send_todo(_dt(2026, 10, 14, 8, 0), 8, "", False) is True
    assert should_send_todo(_dt(2026, 10, 14, 8, 0), 8, "2026-10-14", False) is False
    assert should_send_todo(_dt(2026, 10, 14, 9, 0), 8, "", False) is False
    assert should_send_todo(_dt(2026, 10, 14, 8, 0), 8, "", True) is False
