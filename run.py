"""Entry point: loads env, builds store+bot, runs polling.

Usage:
  python run.py --dry-run                  config + self-check, no Telegram
  python run.py --once-vacancy-file FILE   parse a vacancy file, demo-match
                                           against bundled sample CVs
  python run.py                            start the Telegram bot (polling)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobilate.config import Config
from jobilate.dedup import dedup_candidates
from jobilate.matching import score_candidate
from jobilate.models import Candidate, Vacancy
from jobilate.sample_cvs import SAMPLE_CVS, SAMPLE_VACANCY_TEXT
from jobilate.store import Store
from jobilate.telegram_bot import JobilateBot
from jobilate.vacancy_parser import parse_vacancy_text, vagueness


def self_check(cfg: Config) -> list[str]:
    problems: list[str] = []
    try:
        import telegram  # noqa: F401
    except ImportError:
        problems.append("python-telegram-bot is not installed (pip install -r requirements.txt)")
    try:
        import requests  # noqa: F401
        import bs4  # noqa: F401
    except ImportError:
        problems.append("requests / beautifulsoup4 not installed")
    # Parser + matching smoke test on the bundled sample.
    parsed = parse_vacancy_text(SAMPLE_VACANCY_TEXT)
    if parsed.get("title") != "Sales Supervisor":
        problems.append(f"parser smoke test failed: title={parsed.get('title')!r}")
    scored = [score_candidate(parsed, cv) for cv in SAMPLE_CVS]
    if not any(t == "Tier1" for _, t, _ in scored):
        problems.append("matching smoke test failed: no Tier1 for Sample 1")
    return problems


def demo_match(vacancy_file: str | None) -> dict:
    if vacancy_file:
        with open(vacancy_file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = SAMPLE_VACANCY_TEXT
    parsed = parse_vacancy_text(text)
    results = []
    for cv in dedup_candidates([dict(c) for c in SAMPLE_CVS]):
        score, tier, reason = score_candidate(parsed, cv)
        results.append({"name": cv["name"], "title": cv["title"], "score": round(score, 1), "tier": tier, "reason": reason})
    results.sort(key=lambda r: -r["score"])
    return {"parsed_vacancy": parsed, "vagueness": vagueness(parsed), "matches": results}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Jobilate recruiter bot")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once-vacancy-file", metavar="PATH")
    args = ap.parse_args(argv)
    cfg = Config.from_env()
    if args.dry_run:
        print("Jobilate recruiter bot — dry run")
        print(f"DATA_DIR={cfg.data_dir}")
        print(f"ADMIN_CHAT_ID={'set' if cfg.admin_chat_id else 'MISSING'}")
        print(f"BOT_TOKEN={'set' if cfg.bot_token else 'MISSING'}")
        print(f"QUIET_HOURS={cfg.quiet_hours_start:02d}:00–{cfg.quiet_hours_end:02d}:00")
        print(f"SCRAPE_MIN_DELAY={cfg.scrape_min_delay_seconds}s CACHE_TTL={cfg.cache_ttl_minutes} min")
        problems = self_check(cfg)
        if problems:
            print("SELF-CHECK FAILED:")
            for p in problems:
                print(" -", p)
            return 1
        print("SELF-CHECK OK: parser + matching smoke tests passed.")
        print("HARD LIMIT: bot never contacts candidates; sends only to recruiter chat.")
        return 0
    if args.once_vacancy_file is not None:
        import json
        out = demo_match(args.once_vacancy_file)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    problems = cfg.validate(need_token=True)
    if problems:
        print("Config problems:")
        for p in problems:
            print(" -", p)
        return 2
    store = Store(cfg.db_path)
    bot = JobilateBot(cfg, store)
    app = bot.build_application()
    print("Starting Jobilate recruiter bot (polling)…")
    asyncio.run(app.run_polling())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
