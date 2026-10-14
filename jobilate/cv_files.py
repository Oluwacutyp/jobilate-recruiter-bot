"""Per-candidate CV files + harvest ZIPs.

Delivery rule (locked): bulk sends (harvest / dump / export) deliver THREE
things — (1) digest message, (2) real CSV file (opens immediately, no
unzipping), (3) ZIP containing a CSV copy + one CV .txt per candidate +
README.txt with how-to-unzip steps. Live push single: card + one CV .txt.
Live push batch: one digest message + one ZIP with those candidates' CVs.

CV files are plain .txt generated from DB fields (no special app needed
on any phone). Filenames are sanitized — no slashes, no spaces, no
path traversal. No secrets ever go into CV files or ZIPs.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile

from .csv_export import CSV_COLUMNS, links_to_rows

# Telegram document cap safety: never send a ZIP bigger than this.
# Text CVs are tiny, so this is a safety cap, not an expected path.
MAX_ZIP_BYTES = 45 * 1024 * 1024

UNZIP_README_TEXT = """Jobilate — how to open your files
==================================

You got 3 things from the bot:
1. Digest (the message) — scan it quickly to see who matched.
2. CSV file — open it right now, no unzipping needed. Full list in a table.
3. ZIP file (this pack) — the full pack: a CSV copy + one CV .txt file
   per candidate + this README. Open it when you want the full CVs.

How to unzip the ZIP:
- Android: tap the ZIP in Telegram -> tap Extract, or open it with the
  Files app -> long-press the ZIP -> Extract. The CV files appear next
  to it as .txt files. Tap any .txt to read it.
- iPhone: tap the ZIP -> Preview -> Share -> Save to Files -> open Files,
  long-press the ZIP -> Uncompress. The CV files appear next to it.
- Windows: right-click the ZIP -> Extract All -> Extract. Open the
  folder and double-click any .txt file to read it.

CV files are named cv_<candidate_id>_<name>.txt — one per candidate.
Each CV has: name, phone number, title, location, education, highest
qualification, experience, skills, languages, certifications, expected
salary, match reason, tier/score, and the original CV link.

Remember: the bot never contacts candidates. You text them yourself.
"""


def zip_exceeds_cap(nbytes: int) -> bool:
    """True when a ZIP is too big to send (over the 45MB safety cap)."""
    return nbytes > MAX_ZIP_BYTES


def safe_filename_component(value: str, fallback: str = "candidate") -> str:
    """Sanitize one filename component: alphanumeric + _ + - only.

    Strips slashes, spaces, dots and anything else that could escape
    the ZIP (e.g. '../..' becomes a harmless flat name).
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "")).strip("_")
    cleaned = cleaned[:40] or fallback
    return cleaned


def _get(link: dict, candidate, *keys, default: str = ""):
    """Read a field from a Candidate object first, else from the link dict."""
    if candidate is not None:
        for key in keys:
            val = getattr(candidate, key, None)
            if val is not None and val != "":
                return val
    for key in keys:
        val = link.get(key)
        if val is not None and val != "":
            return val
    return default


def cv_filename(link: dict) -> str:
    """cv_<candidate_id>_<safe_name>.txt — no slashes, no spaces."""
    cid = link.get("candidate_id")
    if cid is None:
        cid = link.get("id", 0)
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        cid = 0
    name = _get(link, None, "name", default="candidate")
    return f"cv_{cid}_{safe_filename_component(name)}.txt"


def cv_text_for_link(link: dict, candidate=None) -> str:
    """Human-readable CV .txt for one candidate link (from DB fields)."""
    name = _get(link, candidate, "name", default="Unknown")
    title = _get(link, candidate, "ctitle", "title", default="—")
    phone = _get(link, candidate, "phone", default="—")
    location = _get(link, candidate, "cloc", "location", default="—")
    job_type = _get(link, candidate, "job_type", default="—")
    employment = _get(link, candidate, "employment_status", default="—")
    education = _get(link, candidate, "education", default="—")
    highest = _get(link, candidate, "highest_qualification", default="—")
    exp_years = _get(link, candidate, "experience_years", default="—")
    exp_text = _get(link, candidate, "experience_text", default="—")
    skills = _get(link, candidate, "skills", default="—")
    languages = _get(link, candidate, "languages", default="—")
    certs = _get(link, candidate, "certifications", default="—")
    expected = _get(link, candidate, "expected_salary", default="—")
    cv_url = _get(link, candidate, "cv_url", default="—")
    tier = _get(link, candidate, "tier", default="—")
    score = _get(link, candidate, "score", default="—")
    reason = _get(link, candidate, "match_reason", default="—")
    mark = _get(link, candidate, "mark", default="—")
    vacancy_id = link.get("vacancy_id", "")
    vacancy_title = link.get("vacancy_title", "")
    lines = [
        f"CV — {name}",
        f"Title: {title}",
        f"Phone: {phone}",
        f"Location: {location}",
        f"Job type: {job_type}",
        f"Employment status: {employment}",
        f"Education: {education}",
        f"Highest qualification: {highest}",
        f"Experience: {exp_years} years",
        f"Experience detail: {exp_text}",
        f"Skills: {skills}",
        f"Languages: {languages}",
        f"Certifications: {certs}",
        f"Expected salary: {expected}",
        f"Match: {tier} (score {score})",
        f"Why matched: {reason}",
        f"Your mark: {mark}",
    ]
    if vacancy_id != "":
        lines.append(f"For vacancy: #{vacancy_id} {vacancy_title}".strip())
    lines.append(f"Original CV link: {cv_url}")
    lines.append("")
    lines.append("This CV was compiled by the Jobilate bot from the public CV page.")
    lines.append("The bot never contacts candidates. You text them yourself.")
    return "\n".join(lines)


def cv_entries_for_links(links: list[dict], store=None) -> list[tuple[str, str]]:
    """One (filename, text) per UNIQUE candidate (deduped by candidate_id).

    The same candidate can link to several vacancies — one CV file is
    enough; the match reason kept is from the first link seen.
    """
    entries: list[tuple[str, str]] = []
    seen_ids: set = set()
    seen_names: set = set()
    for link in links:
        cid = link.get("candidate_id")
        key = ("id", cid) if cid is not None else ("file", cv_filename(link))
        if key in seen_ids:
            continue
        seen_ids.add(key)
        candidate = None
        if store is not None and cid is not None:
            try:
                candidate = store.get_candidate(int(cid))
            except (TypeError, ValueError):
                candidate = None
        fname = cv_filename(link)
        if fname in seen_names:
            base = fname[:-4]
            n = 2
            while f"{base}_{n}.txt" in seen_names:
                n += 1
            fname = f"{base}_{n}.txt"
        seen_names.add(fname)
        entries.append((fname, cv_text_for_link(link, candidate=candidate)))
    return entries


def csv_bytes_for_links(links: list[dict], vacancy_label: str = "") -> bytes:
    """CSV bytes for links (same columns as write_csv)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    w.writerows(links_to_rows(links, vacancy_label))
    return buf.getvalue().encode("utf-8")


def build_harvest_zip(
    links: list[dict],
    csv_path: str | None = None,
    vacancy_label: str = "",
    csv_bytes: bytes | None = None,
    csv_filename: str = "candidates.csv",
    store=None,
) -> bytes:
    """Build a harvest ZIP: CSV copy + one CV .txt per candidate + README.

    CSV source: csv_path (file on disk) wins, else csv_bytes, else a CSV
    generated from the links. Empty link list still yields a valid ZIP
    (CSV header + README, no CVs) — never crashes.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if csv_path is not None and os.path.exists(csv_path):
            with open(csv_path, "rb") as f:
                zf.writestr(os.path.basename(csv_path), f.read())
        elif csv_bytes is not None:
            zf.writestr(csv_filename, csv_bytes)
        else:
            zf.writestr(csv_filename, csv_bytes_for_links(links, vacancy_label))
        for fname, text in cv_entries_for_links(links, store=store):
            zf.writestr(fname, text)
        readme = UNZIP_README_TEXT
        if vacancy_label:
            readme = f"For: {vacancy_label}\n\n" + readme
        zf.writestr("README.txt", readme)
    return buf.getvalue()
