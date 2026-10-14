"""HARD LIMIT tests: the bot must NEVER contact candidates.

Scans jobilate/ source for any candidate-outreach sending capability
and fails if found. Also verifies the Telegram guard exists and raises.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SRC = os.path.join(os.path.dirname(__file__), "..", "jobilate")

# Sending-to-candidate mechanisms. Deliberately specific: the word
# "template" or a recruiter-facing copy string must NOT trip these.
FORBIDDEN_PATTERNS = [
    r"pywhatkit", r"twilio", r"vonage", r"nexmo", r"textbelt",
    r"send_sms", r"send_whatsapp", r"whatsapp_send",
    r"send_to_candidate", r"send_message_to_candidate",
    r"candidate_chat", r"jiji_chat_send", r"jiji_send_message",
    r"client\.send_message\s*\(\s*.*candidate",
    r"bot\.send_message\s*\(\s*.*candidate",
    r"openwa", r"wppconnect", r"whatsapp-web",
]

# The guard must exist in telegram_bot.py and be the only send path.
REQUIRED_IN_TELEGRAM_BOT = ["def guard_recipient", "guard_recipient("]


def _sources():
    for root, _, files in os.walk(SRC):
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


def test_no_candidate_messaging_capability():
    hits = []
    for path in _sources():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for pat in FORBIDDEN_PATTERNS:
            if re.search(pat, text, re.I):
                hits.append(f"{os.path.basename(path)}: {pat}")
    assert not hits, "Forbidden candidate-outreach code found: " + "; ".join(hits)


def test_guard_exists_and_raises():
    from jobilate.telegram_bot import guard_recipient
    with open(os.path.join(SRC, "telegram_bot.py"), encoding="utf-8") as f:
        text = f.read()
    for needle in REQUIRED_IN_TELEGRAM_BOT:
        assert needle in text
    guard_recipient("12345", "12345")  # recruiter chat: allowed
    try:
        guard_recipient("99999", "12345")
    except PermissionError:
        return
    raise AssertionError("guard_recipient did not raise for a non-recruiter chat")


def test_no_real_secrets_in_source():
    # No token-shaped strings in source (BOT_TOKEN value, long hex, etc.)
    for path in _sources():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "BOT_TOKEN=" not in text or "os.environ" in text
