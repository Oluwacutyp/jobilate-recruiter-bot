""" /edit must accept multi-word values (title=Sales Supervisor)."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobilate.config import Config
from jobilate.models import Vacancy
from jobilate.store import Store
from jobilate.telegram_bot import JobilateBot, parse_edit_fields


def test_parse_single_word_unchanged():
    assert parse_edit_fields("title=Driver") == {"title": "Driver"}


def test_parse_multiword_title():
    assert parse_edit_fields("title=Sales Supervisor") == {"title": "Sales Supervisor"}


def test_parse_two_multiword_fields():
    assert parse_edit_fields("title=Sales Supervisor location=Lagos State") == {
        "title": "Sales Supervisor",
        "location": "Lagos State",
    }


def test_parse_mixed_single_and_multiword():
    assert parse_edit_fields("title=Driver priority=High") == {
        "title": "Driver",
        "priority": "High",
    }


def test_parse_unknown_field_ignored():
    # Unknown foo=bar is not a known field, so nothing is parsed;
    # the handler then reports "Nothing updated" as before.
    assert parse_edit_fields("foo=bar") == {}


def _bot_with_vacancy():
    db = tempfile.mktemp(suffix=".db")
    store = Store(db)
    vid = store.add_vacancy(Vacancy(title="Old", location="Abuja", status="active"))
    bot = JobilateBot(Config(bot_token="x", admin_chat_id="1"), store)
    return bot, store, vid, db


class _Msg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)


class _Update:
    def __init__(self, msg):
        self.message = msg


class _Ctx:
    def __init__(self, args):
        self.args = args


def _run_edit(bot, args):
    msg = _Msg()
    asyncio.run(bot.cmd_edit(_Update(msg), _Ctx(args)))
    return msg.texts


def test_cmd_edit_multiword_title_end_to_end():
    bot, store, vid, db = _bot_with_vacancy()
    try:
        texts = _run_edit(bot, ["1", "title=Sales", "Supervisor"])
        assert texts == [f"Updated #{vid}."]
        assert store.get_vacancy(vid).title == "Sales Supervisor"
    finally:
        store.close()
        os.unlink(db)


def test_cmd_edit_two_multiword_fields_end_to_end():
    bot, store, vid, db = _bot_with_vacancy()
    try:
        _run_edit(bot, ["1", "title=Sales", "Supervisor", "location=Lagos", "State"])
        v = store.get_vacancy(vid)
        assert v.title == "Sales Supervisor"
        assert v.location == "Lagos State"
    finally:
        store.close()
        os.unlink(db)


def test_cmd_edit_single_word_still_works():
    bot, store, vid, db = _bot_with_vacancy()
    try:
        _run_edit(bot, ["1", "title=Driver"])
        assert store.get_vacancy(vid).title == "Driver"
    finally:
        store.close()
        os.unlink(db)


def test_cmd_edit_unknown_field_nothing_updated():
    bot, store, vid, db = _bot_with_vacancy()
    try:
        texts = _run_edit(bot, ["1", "foo=bar"])
        assert texts == ["Nothing updated — check field names."]
        assert store.get_vacancy(vid).title == "Old"
    finally:
        store.close()
        os.unlink(db)
