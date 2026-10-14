"""Long-message chunking: /harvest digest (and every long send) must never
hit Telegram's 4096-char 'Message is too long' BadRequest.

All Telegram calls are faked; the fakes ENFORCE the 4096 limit (raise
'Message is too long' like the real API) so a missing chunk would fail
the test exactly the way it failed in production (2026-10-14).
"""
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.config import Config
from jobilate.csv_export import build_digest
from jobilate.models import Candidate, Vacancy
from jobilate.store import Store
from jobilate.telegram_bot import (
    MAX_TELEGRAM_TEXT,
    JobilateBot,
    send_to_recruiter,
    split_long_message,
)


def _run(coro):
    return asyncio.run(coro)


class _TooLongError(Exception):
    pass


def _enforcing_reply_factory(calls):
    """Fake update.message.reply_text that rejects >4096 chars like Telegram."""
    async def reply_text(text, **kwargs):
        if len(text) > 4096:
            raise _TooLongError("Message is too long")
        calls.append(text)
        return None
    return reply_text


class _FakeUpdate:
    def __init__(self, chat_id="123"):
        self.message = SimpleNamespace(
            text="", replies=[], documents=[],
            reply_text=None, reply_document=None)
        self.message.reply_text = _enforcing_reply_factory(self.message.replies)
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.callback_query = None

    async def reply_document(self, **kwargs):
        self.message.documents.append(kwargs)


# reply_document is looked up on update.message in the bot code, so wire it.
def _wire_doc(upd):
    async def reply_document(**kwargs):
        upd.message.documents.append(kwargs)
        return None
    upd.message.reply_document = reply_document
    return upd


def _bot(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    return JobilateBot(Config(bot_token="x", admin_chat_id="123"), store), store


# ---- 1. splitter: 10KB digest -> >=3 chunks, each <=4000, lossless ----
def test_split_10kb_lossless():
    lines = [f"Candidate {i:03d} — Sales Rep, Lagos, B.Tech, 5 years experience, reason number {i}" for i in range(150)]
    text = "\n".join(lines)
    assert len(text) > 10_000
    chunks = split_long_message(text)
    assert len(chunks) >= 3
    assert all(len(c) <= MAX_TELEGRAM_TEXT for c in chunks)
    assert "".join(chunks) == text


# ---- 2. short text -> exactly one message, unchanged ----
def test_split_short_single():
    assert split_long_message("hello") == ["hello"]
    assert split_long_message("") == []


# ---- 3. split prefers newline boundaries; over-long line hard-split ----
def test_split_newline_boundaries():
    lines = [f"line {i:03d} " + ("x" * 80) for i in range(100)]
    text = "\n".join(lines)
    chunks = split_long_message(text)
    # Every chunk except the last ends at a line boundary (trailing newline).
    assert all(c.endswith("\n") for c in chunks[:-1])
    assert "".join(chunks) == text
    # One 9000-char line (no newlines at all): hard-split, still lossless.
    long_line = "y" * 9000
    chunks2 = split_long_message(long_line)
    assert len(chunks2) == 3
    assert all(len(c) <= MAX_TELEGRAM_TEXT for c in chunks2)
    assert "".join(chunks2) == long_line


# ---- 4a. _reply_long chunks a long reply through an enforcing fake ----
def test_reply_long_chunks(tmp_path):
    bot, _ = _bot(tmp_path)
    upd = _wire_doc(_FakeUpdate())
    ctx = SimpleNamespace(args=[], user_data={}, bot=SimpleNamespace())
    text = "\n".join(f"row {i} " + ("z" * 90) for i in range(100))
    _run(bot._reply_long(upd, text))
    assert len(upd.message.replies) >= 3
    assert all(len(r) <= 4000 for r in upd.message.replies)
    assert "".join(upd.message.replies) == text


# ---- 4b. safety net: an oversized chunk is retried truncated, not fatal ----
def test_reply_long_safety_net_truncates(tmp_path, monkeypatch):
    bot, _ = _bot(tmp_path)
    calls = []

    async def reply_text(text, **kwargs):
        if len(text) > 4096:
            raise _TooLongError("Message is too long")
        calls.append(text)
        return None

    upd = SimpleNamespace(message=SimpleNamespace(reply_text=reply_text),
                          effective_chat=SimpleNamespace(id="123"))
    # Simulate a splitter miss: force one 5000-char chunk.
    monkeypatch.setattr(
        "jobilate.telegram_bot.split_long_message",
        lambda text, limit=MAX_TELEGRAM_TEXT: ["Q" * 5000])
    _run(bot._reply_long(upd, "ignored"))
    assert len(calls) == 1
    assert calls[0] == "Q" * (MAX_TELEGRAM_TEXT - 3) + "..."


# ---- 5. /harvest with 100 candidates: no BadRequest, digest in parts ----
def test_cmd_harvest_100_candidates_no_badrequest(tmp_path):
    bot, store = _bot(tmp_path)
    vid = store.add_vacancy(Vacancy(title="Sales Supervisor", location="Lagos State", status="active"))
    for i in range(100):
        cid = store.add_or_get_candidate(Candidate(
            name=f"Candidate {i:03d}", phone=f"+234800000{i:04d}",
            title="Sales Rep", location="Lagos",
            cv_url=f"https://jiji.ng/cv-{i}"))
        store.link_candidate(vid, cid, 80, "Tier1",
                             f"Strong match: B.Tech plus 5 years agro-pharma sales, candidate {i}")
    upd = _wire_doc(_FakeUpdate())
    ctx = SimpleNamespace(args=[str(vid)], user_data={}, bot=SimpleNamespace())
    _run(bot.cmd_harvest(upd, ctx))  # must NOT raise BadRequest
    replies = upd.message.replies
    assert replies, "harvest sent no digest"
    assert all(len(r) <= 4000 for r in replies)
    joined = "".join(replies)
    assert "Candidate 000" in joined and "Candidate 099" in joined
    # Digest + CSV + ZIP all delivered (CSV/ZIP are documents, digest is text).
    assert upd.message.documents, "harvest sent no CSV/ZIP documents"


# ---- 6. send_to_recruiter chunks bot-side sends too ----
def test_send_to_recruiter_chunks():
    calls = []

    async def send_message(chat_id, text, **kwargs):
        if len(text) > 4096:
            raise _TooLongError("Message is too long")
        calls.append(text)
        return None

    ctx = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
    text = "\n".join(f"line {i} " + ("w" * 90) for i in range(100))
    _run(send_to_recruiter(ctx, "123", text, "123"))
    assert len(calls) >= 3
    assert all(len(c) <= 4000 for c in calls)
    assert "".join(calls) == text
    # Short text still sends as exactly one message.
    calls.clear()
    _run(send_to_recruiter(ctx, "123", "hi", "123"))
    assert calls == ["hi"]
