"""Harvest: incremental delivery + flags. Bot never dumps by default.

Modes:
  incremental (default /harvest [vacancy]): only harvested_to_her=False,
      then mark those links harvested.
  unsent: sent_by_her=False (she has not texted them yet).
  unsent_employer: sent_to_employer=False.
  all (/dump): everything.
Harvest returns (links, digest_text) and marks harvested only for the
incremental mode — /harvest unsent does not mark harvested.
"""
from __future__ import annotations

from .csv_export import build_digest
from .store import Store


def harvest(store: Store, vacancy_id: int | None = None, mode: str = "incremental") -> tuple[list[dict], str]:
    links = store.all_links() if vacancy_id is None else store.links_for_vacancy(vacancy_id)
    if mode == "incremental":
        picked = [ln for ln in links if not ln.get("harvested_to_her")]
        store.mark_harvested([ln["id"] for ln in picked])
    elif mode == "unsent":
        picked = [ln for ln in links if not ln.get("sent_by_her")]
    elif mode == "unsent_employer":
        picked = [ln for ln in links if not ln.get("sent_to_employer")]
    elif mode == "all":
        picked = list(links)
    else:
        raise ValueError(f"unknown harvest mode: {mode!r}")
    if vacancy_id is not None:
        vac = store.get_vacancy(vacancy_id)
        label = vac.label() if vac else f"#{vacancy_id}"
    else:
        label = "All vacancies"
    return picked, build_digest(picked, label)


def harvest_counts(store: Store, vacancy_id: int | None = None) -> dict:
    links = store.all_links() if vacancy_id is None else store.links_for_vacancy(vacancy_id)
    return {
        "total": len(links),
        "unharvested": sum(1 for ln in links if not ln.get("harvested_to_her")),
        "unsent": sum(1 for ln in links if not ln.get("sent_by_her")),
        "unsent_employer": sum(1 for ln in links if not ln.get("sent_to_employer")),
    }
