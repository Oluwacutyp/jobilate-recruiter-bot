"""CF_CLEARANCE diagnostics + Edge UA + 'Chrome' string fix (2026-10-14).

User-verified: bot said "Try real Chrome profile" (should be Edge),
default UA was Edge 126 while the user's Edge is 155 (cookie solved
with 155 UA + bot sending 126 UA -> Cloudflare may reject it), and
the user had NO way to verify the bot sees his CF_CLEARANCE.

All tests mocked — never hit live Jiji, never contain a real cookie.
Fake cookie values are placeholders only.
"""
import asyncio
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.browser_fetch import (
    DEFAULT_USER_AGENT,
    _dotenv_candidates,
    _read_dotenv_value,
    cf_clearance_status,
    read_cf_clearance,
)
from jobilate.config import Config
from jobilate.store import Store
from jobilate.telegram_bot import JobilateBot


def _run(coro):
    return asyncio.run(coro)


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class _FakeUpdate:
    def __init__(self):
        self.message = _FakeMessage()
        self.effective_chat = SimpleNamespace(id="123")
        self.callback_query = None


class _FakeContext:
    def __init__(self):
        self.args = []
        self.user_data = {}
        self.bot = SimpleNamespace()


def _bot(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    return JobilateBot(Config(bot_token="x", admin_chat_id="123"), store)


def _config_text(bot):
    upd, ctx = _FakeUpdate(), _FakeContext()
    _run(bot.cmd_config(upd, ctx))
    assert upd.message.replies, "/config sent nothing"
    return upd.message.replies[0]


# ---- 1. /config shows set / not-set WITHOUT the value ----
def test_config_shows_cf_clearance_not_set(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CF_CLEARANCE", raising=False)
    monkeypatch.delenv("DOTENV_PATH", raising=False)
    text = _config_text(_bot(tmp_path))
    assert "CF_CLEARANCE: NOT SET" in text
    assert "BROWSER_CHANNELS: msedge" in text
    assert "JIJI_USER_AGENT:" in text
    assert ".env path checked:" in text


def test_config_shows_cf_clearance_set_without_value(tmp_path, monkeypatch):
    secret = "cf-clearance-FAKE-VALUE-12345"
    (tmp_path / ".env").write_text(f"CF_CLEARANCE={secret}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CF_CLEARANCE", raising=False)
    monkeypatch.delenv("DOTENV_PATH", raising=False)
    text = _config_text(_bot(tmp_path))
    assert f"CF_CLEARANCE: set (len {len(secret)}, from .env file)" in text
    assert secret not in text, "cookie value must NEVER appear in /config output"
    assert "JIJI_USER_AGENT:" in text


def test_cf_clearance_status_never_returns_value(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("CF_CLEARANCE=some-fake-secret\n", encoding="utf-8")
    status = cf_clearance_status(str(dotenv))
    assert status["set"] is True
    assert status["length"] == len("some-fake-secret")
    assert "some-fake-secret" not in str(status)


# ---- 2. Default UA is current Edge (>= 131), not stale 126 ----
def test_default_ua_is_current_edge_not_126():
    assert "Edg/" in DEFAULT_USER_AGENT
    m = re.search(r"Edg/(\d+)", DEFAULT_USER_AGENT)
    assert m, "default UA has no Edg/ version"
    assert int(m.group(1)) >= 131, f"default Edge UA is stale: {DEFAULT_USER_AGENT}"
    assert "126" not in DEFAULT_USER_AGENT


# ---- 3. .env.txt is ignored (Notepad "Text Documents" trap) ----
def test_dotenv_candidates_never_include_env_txt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOTENV_PATH", raising=False)
    candidates = _dotenv_candidates(None)
    assert candidates, "expected at least one .env candidate"
    assert all(not c.endswith(".env.txt") for c in candidates)
    assert any(c.endswith(".env") for c in candidates)


def test_env_txt_file_is_ignored(tmp_path, monkeypatch):
    # A file named .env.txt with a secret must NOT be read as .env.
    (tmp_path / ".env.txt").write_text("CF_CLEARANCE=txt-trap-secret\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CF_CLEARANCE", raising=False)
    monkeypatch.delenv("DOTENV_PATH", raising=False)
    # Explicit .env path in tmp (missing) -> only repo-root .env could
    # match; the repo tree has no .env, so this must be "".
    assert read_cf_clearance(str(tmp_path / ".env")) == ""


# ---- 4. Multi-line / truncated CF_CLEARANCE reads as first line only ----
def test_multiline_cf_clearance_reads_first_line_only(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("CF_CLEARANCE=first-part\nsecond-part\n", encoding="utf-8")
    assert _read_dotenv_value("CF_CLEARANCE", str(dotenv)) == "first-part"
    assert read_cf_clearance(str(dotenv)) == "first-part"


def test_quoted_cf_clearance_stripped(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text('CF_CLEARANCE="quoted-fake"\n', encoding="utf-8")
    assert read_cf_clearance(str(dotenv)) == "quoted-fake"


# ---- 5. No leftover "Chrome profile" string (must be Edge) ----
def test_no_chrome_profile_string_in_browser_fetch():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "jobilate", "browser_fetch.py"),
        encoding="utf-8",
    ).read()
    assert "Try real Chrome profile" not in src
    assert "Try real Edge profile" in src
