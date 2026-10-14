"""Live push: send-as-it-gets, with smart batching + quiet hours.

Rules (locked): Tier1 sends immediately; the rest batch every
live_batch_minutes OR every live_batch_size new matches. Live pushes
send CARD ONLY — no CSV file each time (spam). Card carries the note
'CSV updated — use /harvest for full CSV'. Quiet hours respected.
Per-vacancy live on/off; global live-off = harvest-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime


def in_quiet_hours(now: datetime, start: int, end: int) -> bool:
    """Quiet hours wrap midnight (e.g. 22 -> 07)."""
    t = now.time()
    s, e = dtime(hour=start), dtime(hour=end)
    if start == end:
        return False
    if start < end:
        return s <= t < e
    return t >= s or t < e


def format_card(link: dict, vacancy_label: str, other_matches: list[str] | None = None) -> str:
    lines = [
        f"🆕 {link.get('tier', '')} · {vacancy_label}",
        f"{link.get('name', '')} — {link.get('ctitle', '')}",
        f"📞 {link.get('phone', '')} · 📍 {link.get('cloc', '')}",
    ]
    if link.get("highest_qualification"):
        lines.append(f"🎓 {link['highest_qualification']}")
    if link.get("experience_years") is not None:
        lines.append(f"💼 {link['experience_years']}y experience")
    if link.get("expected_salary"):
        lines.append(f"💰 Expects: {link['expected_salary']}")
    if link.get("match_reason"):
        lines.append(f"Why: {link['match_reason']}")
    if other_matches:
        lines.append("Also matches: " + ", ".join(other_matches))
    if link.get("cv_url"):
        lines.append(f"CV: {link['cv_url']}")
    lines.append("CSV updated — use /harvest for full CSV")
    return "\n".join(lines)


@dataclass
class LivePushQueue:
    """Per-vacancy batching queue. Tier1 bypasses the batch."""

    batch_minutes: int = 5
    batch_size: int = 5
    _pending: dict[int, list[dict]] = field(default_factory=dict, repr=False)
    _last_flush: dict[int, datetime] = field(default_factory=dict, repr=False)

    def add(self, vacancy_id: int, link: dict) -> tuple[list[dict], list[dict]]:
        """Add a match. Returns (immediate, batched_due).

        immediate: Tier1 links, sent at once.
        batched_due: pending links released because size/time threshold hit.
        """
        if link.get("tier") == "Tier1":
            return [link], []
        self._pending.setdefault(vacancy_id, []).append(link)
        pending = self._pending[vacancy_id]
        due: list[dict] = []
        if len(pending) >= self.batch_size:
            due = pending[:]
            self._pending[vacancy_id] = []
            self._last_flush[vacancy_id] = datetime.now()
        return [], due

    def due_by_time(self, vacancy_id: int, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now()
        pending = self._pending.get(vacancy_id, [])
        if not pending:
            return []
        last = self._last_flush.get(vacancy_id)
        if last is None or (now - last).total_seconds() >= self.batch_minutes * 60:
            self._pending[vacancy_id] = []
            self._last_flush[vacancy_id] = now
            return pending
        return []

    def pending_count(self, vacancy_id: int) -> int:
        return len(self._pending.get(vacancy_id, []))
