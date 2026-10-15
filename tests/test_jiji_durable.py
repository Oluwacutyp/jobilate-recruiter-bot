"""Durable Jiji access tests (2026-10-15): block-notice dedupe +
stale-cookie hint. No live Jiji, no real Telegram, no real cookies.
"""
import asyncio
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.config import Config
from jobilate.models import Vacancy
from jobilate.store import Store
from jobilate.telegram_bot import (
    _stale_cookie_suffix,
    block_error_signature,
    JobilateBot,
)

BLOCK_A = (
    "Cloudflare 'Just a moment...' challenge — bot's browser was flagged "
    "as automated. for https://jiji.ng/seeking-work-cvs?query=Spa+therapist+sales+Lagos "
    "diag: title='Just a moment...' anchors=2 html_len=28889 flags=none"
)
# Same block, different query + diag numbers (what the 2026-10-15
# screenshot showed twice) -> SAME signature.
BLOCK_B = (
    "Cloudflare 'Just a moment...' challenge — bot's browser was flagged "
    "as automated. for https://jiji.ng/seeking-work-cvs?query=Sales+supervisor+Lagos "
    "diag: title='Just a moment...' anchors=2 html_len=29248 flags=none"
)


def test_signature_normalises_url_and_diag():
    assert block_error_signature(BLOCK_A) == "cloudflare-block"
    assert block_error_signature(BLOCK_A) == block_error_signature(BLOCK_B)


def test_signature_keeps_distinct_errors_distinct():
    assert block_error_signature("Jiji returned HTTP 403 for xyz") != block_error_signature(
        "Jiji page structure changed: no CV cards found"
    )


def _bot(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    return JobilateBot(Config(bot_token="x", admin_chat_id="1", data_dir=str(tmp_path)), store), store


def test_should_send_block_notice_dedupes_within_5min(tmp_path):
    bot, _ = _bot(tmp_path)
    assert bot._should_send_block_notice("cloudflare-block") is True
    assert bot._should_send_block_notice("cloudflare-block") is False  # duplicate, suppressed
    assert bot._should_send_block_notice("http-403") is True  # distinct signature still sent
    # After the window passes, the same signature may be sent again.
    bot._last_block_notice["cloudflare-block"] = time.monotonic() - 301
    assert bot._should_send_block_notice("cloudflare-block") is True


class _Msg:
    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class _Upd:
    def __init__(self):
        self.message = _Msg()
        self.effective_chat = SimpleNamespace(id=1)


class _Ctx:
    def __init__(self):
        self.args: list[str] = []
        self.bot = SimpleNamespace()


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _add_vacancy(store, title):
    return store.add_vacancy(Vacancy(title=title, location="Lagos", status="active"))


def test_cmd_scrape_dedupes_identical_block_across_vacancies(tmp_path, monkeypatch):
    """One /scrape over 2 vacancies hitting the same Cloudflare block
    used to send the identical error twice (screenshot 2026-10-15).
    Now: one notice."""
    import jobilate.telegram_bot as tb

    bot, store = _bot(tmp_path)
    _add_vacancy(store, "Spa therapist")
    _add_vacancy(store, "Sales supervisor")

    async def _fake_scrape(store_, vacancy, scraper, max_cards=20):
        return [], BLOCK_A

    monkeypatch.setattr(tb, "scrape_one_vacancy_async", _fake_scrape)
    upd, ctx = _Upd(), _Ctx()
    _run(bot.cmd_scrape(upd, ctx))
    blocked = [r for r in upd.message.replies if "Jiji blocked" in r]
    assert len(blocked) == 1, f"expected 1 deduped notice, got {len(blocked)}: {upd.message.replies}"


def test_cmd_scrape_dedupes_repeat_within_5min(tmp_path, monkeypatch):
    import jobilate.telegram_bot as tb

    bot, store = _bot(tmp_path)
    _add_vacancy(store, "Spa therapist")

    async def _fake_scrape(store_, vacancy, scraper, max_cards=20):
        return [], BLOCK_A

    monkeypatch.setattr(tb, "scrape_one_vacancy_async", _fake_scrape)
    upd1, ctx = _Upd(), _Ctx()
    _run(bot.cmd_scrape(upd1, ctx))
    assert any("Jiji blocked" in r for r in upd1.message.replies)
    upd2, ctx2 = _Upd(), _Ctx()
    _run(bot.cmd_scrape(upd2, ctx2))
    assert not any("Jiji blocked" in r for r in upd2.message.replies), (
        "second identical block within 5 min must be suppressed"
    )


def test_stale_cookie_suffix_never_contains_value(tmp_path, monkeypatch):
    """The hint never leaks the cookie value, even when one is set."""
    import jobilate.browser_fetch as bf

    monkeypatch.setattr(bf, "cf_clearance_status", lambda: {"set": True, "length": 597, "source": ".env file", "env_path": "/x/.env"})
    suffix = _stale_cookie_suffix()
    assert "cf_clearance" in suffix.lower() or "cookie" in suffix.lower()
    assert "597" not in suffix  # length must not leak either (keeps /config the only place)
    assert "stale" in suffix.lower()
    monkeypatch.setattr(bf, "cf_clearance_status", lambda: {"set": False, "length": 0, "source": "", "env_path": "/x/.env"})
    assert _stale_cookie_suffix() == ""


def test_no_telegram_cookie_command():
    """No command may accept a cookie value over Telegram (it would
    leak in chat history). The refresh path is .env on the RDP only."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "jobilate", "telegram_bot.py"), encoding="utf-8").read()
    assert "refreshcookie" not in src.lower()
    # No handler parses a cookie from a chat message.
    assert "cmd_cookie" not in src
