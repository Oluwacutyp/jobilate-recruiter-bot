"""Dedup: one candidate record, many vacancy links.

Phone is the primary key (normalised); name+title is the fallback.
Cross-vacancy dedup means the same person linked to two vacancies is
ONE candidate row with TWO links, tagged 'also matches [Other]'.
"""
from __future__ import annotations

import re


def normalize_phone(phone: str) -> str:
    """Normalise to digits, keeping a leading + when present."""
    p = re.sub(r"[\s\-()]", "", (phone or "").strip())
    if p.startswith("+"):
        return "+" + re.sub(r"\D", "", p[1:])
    digits = re.sub(r"\D", "", p)
    if digits.startswith("0") and len(digits) == 11:
        # Nigerian local format 0XXX... -> +234 XXX...
        return "+234" + digits[1:]
    if digits.startswith("234") and len(digits) == 13:
        return "+" + digits
    return digits


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").lower().strip())


def candidate_key(name: str, phone: str, title: str = "") -> str:
    """Stable dedup key: phone when present, else name+title."""
    ph = normalize_phone(phone)
    if ph and ph not in ("", "+"):
        return "phone:" + ph
    return "name:" + normalize_name(name) + "|" + re.sub(r"\s+", " ", (title or "").lower().strip())


def dedup_candidates(cands: list[dict]) -> list[dict]:
    """Dedupe a list of candidate dicts, keeping the first occurrence."""
    seen: dict[str, dict] = {}
    for c in cands:
        key = candidate_key(c.get("name", ""), c.get("phone", ""), c.get("title", ""))
        if key not in seen:
            seen[key] = c
        else:
            # Merge: fill empty fields from the duplicate.
            for k, v in c.items():
                if not seen[key].get(k) and v:
                    seen[key][k] = v
    return list(seen.values())
