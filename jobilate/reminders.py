"""Reminders + daily to-do. Pure functions over store rows — no sending."""
from __future__ import annotations

from datetime import datetime, timezone

from .store import Store


def _parse_iso(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def followups_due(store: Store, days: int = 3, now: datetime | None = None) -> list[dict]:
    """Links marked Texted >= `days` ago with no newer mark (no reply)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for ln in store.all_links():
        if ln.get("mark") != "Texted":
            continue
        marked = _parse_iso(ln.get("marked_at") or "")
        if marked and (now - marked).days >= days:
            out.append(ln)
    return out


def daily_todo(store: Store) -> str:
    """One readable to-do list: unharvested, untexted, follow-ups, shortlist."""
    lines = ["📝 Today's to-do"]
    n_unharvested = sum(1 for ln in store.all_links() if not ln.get("harvested_to_her"))
    n_untexted = sum(1 for ln in store.all_links() if not ln.get("sent_by_her") and ln.get("mark") != "Not fit")
    n_follow = len(followups_due(store))
    n_interested = sum(1 for ln in store.all_links() if ln.get("mark") == "Interested")
    lines.append(f"• {n_unharvested} new candidate(s) to review — /harvest")
    lines.append(f"• {n_untexted} candidate(s) not yet texted")
    lines.append(f"• {n_follow} follow-up(s) due (texted 3+ days ago, no reply)")
    lines.append(f"• {n_interested} interested candidate(s) — consider /shortlist")
    for vac in store.list_vacancies(status="active"):
        st = store.stats_for_vacancy(vac.id)
        lines.append(f"• {vac.label()}: {st['total']} candidates ({st.get('Tier1', 0)} Tier1)")
    return "\n".join(lines)
