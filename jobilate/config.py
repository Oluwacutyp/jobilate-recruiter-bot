"""Configuration — secrets ONLY via environment variables. Never hardcode."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    bot_token: str = ""
    admin_chat_id: str = ""
    data_dir: str = "./data"
    quiet_hours_start: int = 22
    quiet_hours_end: int = 7
    scrape_min_delay_seconds: float = 3.0
    cache_ttl_minutes: int = 15
    live_batch_minutes: int = 5
    live_batch_size: int = 5

    @classmethod
    def from_env(cls) -> "Config":
        def _int(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, str(default)))
            except ValueError:
                return default

        def _float(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, str(default)))
            except ValueError:
                return default

        return cls(
            bot_token=os.environ.get("BOT_TOKEN", ""),
            admin_chat_id=os.environ.get("ADMIN_CHAT_ID", ""),
            data_dir=os.environ.get("DATA_DIR", "./data"),
            quiet_hours_start=_int("QUIET_HOURS_START", 22),
            quiet_hours_end=_int("QUIET_HOURS_END", 7),
            scrape_min_delay_seconds=_float("SCRAPE_MIN_DELAY_SECONDS", 3.0),
            cache_ttl_minutes=_int("CACHE_TTL_MINUTES", 15),
            live_batch_minutes=_int("LIVE_BATCH_MINUTES", 5),
            live_batch_size=_int("LIVE_BATCH_SIZE", 5),
        )

    def validate(self, need_token: bool = True) -> list[str]:
        problems: list[str] = []
        if need_token and not self.bot_token:
            problems.append("BOT_TOKEN is not set")
        if not self.admin_chat_id:
            problems.append("ADMIN_CHAT_ID is not set (recruiter chat id)")
        if not (0 <= self.quiet_hours_start <= 23):
            problems.append("QUIET_HOURS_START must be 0-23")
        if not (0 <= self.quiet_hours_end <= 23):
            problems.append("QUIET_HOURS_END must be 0-23")
        if self.scrape_min_delay_seconds < 3.0:
            problems.append("SCRAPE_MIN_DELAY_SECONDS must be >= 3")
        return problems

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "jobilate.db")
