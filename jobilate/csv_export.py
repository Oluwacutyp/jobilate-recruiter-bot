"""CSV export + readable digest. CSV columns are the contract (see SPEC.md)."""
from __future__ import annotations

import csv
import os

CSV_COLUMNS = ["vacancy_id", "vacancy_title", "candidate_id", "name", "phone", "candidate_title", "location", "highest_qualification", "experience_years", "expected_salary", "skills", "cv_url", "score", "tier", "match_reason", "mark", "marked_at", "sent_by_her", "sent_to_employer", "harvested_to_her"]


def links_to_rows(links: list[dict], vacancy_title: str = "") -> list[dict]:
    rows = []
    for ln in links:
        rows.append({
            "vacancy_id": ln.get("vacancy_id", ""),
            "vacancy_title": vacancy_title or ln.get("vacancy_title", ""),
            "candidate_id": ln.get("candidate_id", ""),
            "name": ln.get("name", ""),
            "phone": ln.get("phone", ""),
            "candidate_title": ln.get("ctitle", ln.get("title", "")),
            "location": ln.get("cloc", ln.get("location", "")),
            "highest_qualification": ln.get("highest_qualification", ""),
            "experience_years": ln.get("experience_years", ""),
            "expected_salary": ln.get("expected_salary", ""),
            "skills": ln.get("skills", ""),
            "cv_url": ln.get("cv_url", ""),
            "score": ln.get("score", ""),
            "tier": ln.get("tier", ""),
            "match_reason": ln.get("match_reason", ""),
            "mark": ln.get("mark", ""),
            "marked_at": ln.get("marked_at", ""),
            "sent_by_her": int(bool(ln.get("sent_by_her"))),
            "sent_to_employer": int(bool(ln.get("sent_to_employer"))),
            "harvested_to_her": int(bool(ln.get("harvested_to_her"))),
        })
    return rows


def write_csv(path: str, links: list[dict], vacancy_title: str = "") -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    rows = links_to_rows(links, vacancy_title)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def build_digest(links: list[dict], vacancy_label: str) -> str:
    """Readable Telegram digest: one short block per candidate."""
    if not links:
        return f"{vacancy_label}\nNo candidates in this harvest."
    lines = [f"📋 {vacancy_label} — {len(links)} candidate(s)"]
    for ln in links:
        lines.append("")
        lines.append(f"{ln.get('tier', '')} · {ln.get('name', '')} — {ln.get('ctitle', '')}")
        lines.append(f"📞 {ln.get('phone', '')} · 📍 {ln.get('cloc', '')}")
        if ln.get("match_reason"):
            lines.append(f"Why: {ln.get('match_reason')}")
        if ln.get("cv_url"):
            lines.append(f"CV: {ln.get('cv_url')}")
    return "\n".join(lines)
