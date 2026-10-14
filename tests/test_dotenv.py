"""Tests for run.py .env loader (stdlib-only, no python-dotenv)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobilate.config import Config
from run import load_dotenv


def test_dotenv_parsing(tmp_path, monkeypatch):
    # Pre-existing env wins over .env (setdefault semantics).
    monkeypatch.setenv("BOT_TOKEN", "ENV_WINS_DUMMY")
    for key in ("ADMIN_CHAT_ID", "DATA_DIR", "QUOTED_VAL", "EQUALS_VAL"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    # CRLF line endings (Windows Notepad), comments, blanks, quotes,
    # and a value containing '=' (split on first '=' only).
    env_file.write_bytes(
        b"# comment line\r\n"
        b"\r\n"
        b"BOT_TOKEN=dummy-dotenv-token\r\n"
        b"ADMIN_CHAT_ID=123456789\r\n"
        b'DATA_DIR="./data"\r\n'
        b"QUOTED_VAL='single quoted'\r\n"
        b"EQUALS_VAL=abc=def=ghi\r\n"
        b"MALFORMED LINE WITHOUT EQUALS\r\n"
        b"=empty key\r\n"
    )
    assert load_dotenv(str(env_file)) >= 4
    assert os.environ["BOT_TOKEN"] == "ENV_WINS_DUMMY"
    assert os.environ["ADMIN_CHAT_ID"] == "123456789"
    assert os.environ["DATA_DIR"] == "./data"
    assert os.environ["QUOTED_VAL"] == "single quoted"
    assert os.environ["EQUALS_VAL"] == "abc=def=ghi"
    assert "MALFORMED LINE WITHOUT EQUALS" not in os.environ


def test_dotenv_missing_no_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    assert load_dotenv(str(tmp_path / ".env-does-not-exist")) == 0
    assert "BOT_TOKEN" not in os.environ


def test_config_from_env_reads_os_environ(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "dummy-token-for-config-test")
    monkeypatch.setenv("ADMIN_CHAT_ID", "987654321")
    cfg = Config.from_env()
    assert cfg.bot_token == "dummy-token-for-config-test"
    assert cfg.admin_chat_id == "987654321"
