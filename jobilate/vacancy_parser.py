"""Parse free-form vacancy text (pasted / forwarded) into structured fields.

Accepts lines like:
    Role: Sales Supervisor
    Location: Lagos State
    Pay: 500000+/month
    Requirements: B.Tech ... 5+ years ...
Also handles bare text: first non-empty line becomes the title when no
labelled Role/Title line is present. Returns a dict ready for Store.
"""
from __future__ import annotations

import re

LABEL_RE = re.compile(r"^\s*(role|title|position|location|pay|salary|job type|employment|requirements?|education|experience|employer|company|deadline|contact|priority)\s*[:\-–]\s*(.+)$", re.I)
PAY_RE = re.compile(r"(\d[\d,]*)\s*(?:\+|and\s+above|above|per\s+month|/month|monthly)?", re.I)
YEARS_RE = re.compile(r"(\d+)\s*\+\s*(?:years?|yrs?)", re.I)
EDU_KEYWORDS = ("b.tech", "b.sc", "b.eng", "b.a", "b.agric", "hnd", "ond", "m.sc", "mba", "phd", "ncea", "ssce", "bachelor", "degree", "diploma")
NG_STATES = ("Lagos", "Abuja", "FCT", "Kano", "Kaduna", "Rivers", "Oyo", "Enugu", "Delta", "Ogun", "Anambra", "Imo", "Osun", "Ondo", "Ekiti", "Kwara", "Plateau", "Borno", "Sokoto", "Katsina", "Bauchi", "Benue", "Cross River", "Akwa Ibom", "Bayelsa", "Ebonyi", "Edo", "Gombe", "Jigawa", "Kebbi", "Kogi", "Nasarawa", "Niger", "Taraba", "Yobe", "Zamfara", "Adamawa", "Abia")


def parse_pay(text: str) -> tuple[str, int | None]:
    """Return (pay_text, pay_min). Finds the largest ₦/Naira number in text."""
    nums = [int(m.replace(",", "")) for m in re.findall(r"₦?\s*(\d[\d,]*)", text or "")]
    # Filter out tiny numbers that are years / counts, keep salary-scale ones.
    nums = [n for n in nums if n >= 1000]
    if not nums:
        return (text or "").strip(), None
    return (text or "").strip(), max(nums)


def extract_years(text: str) -> int | None:
    m = YEARS_RE.search(text or "")
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d+)\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)", (text or ""), re.I)
    return int(m2.group(1)) if m2 else None


def extract_education(text: str) -> str:
    low = (text or "").lower()
    found = [k for k in EDU_KEYWORDS if k in low]
    # Keep original-case snippets: return the matched keywords joined.
    return ", ".join(found)


def guess_location(text: str) -> str:
    for state in NG_STATES:
        if re.search(rf"\b{re.escape(state)}\b", text or "", re.I):
            return state + (" State" if state not in ("Abuja", "FCT") else "")
    return ""


def parse_vacancy_text(text: str) -> dict:
    """Parse vacancy text into a field dict. Never raises on junk input."""
    text = (text or "").strip()
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = LABEL_RE.match(line.strip())
        if m:
            key = m.group(1).lower().replace("requirements", "requirements")
            fields[key] = m.group(2).strip()
    title = fields.get("role") or fields.get("title") or fields.get("position") or ""
    if not title:
        for line in text.splitlines():
            if line.strip():
                title = line.strip()[:120]
                break
    location = fields.get("location") or guess_location(text)
    pay_raw = fields.get("pay") or fields.get("salary") or ""
    pay_text, pay_min = parse_pay(pay_raw or text) if pay_raw else ("", None)
    req = fields.get("requirement") or fields.get("requirements") or ""
    if not req:
        # Everything after the title line is requirements when unlabelled.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        req = " ".join(lines[1:]) if len(lines) > 1 else ""
    job_type = fields.get("job type") or fields.get("employment") or "Full-Time"
    priority = fields.get("priority") or "Normal"
    priority = "High" if priority.strip().lower().startswith("high") else "Normal"
    result = {
        "title": title,
        "location": location,
        "pay_text": pay_text,
        "pay_min": pay_min,
        "job_type": job_type,
        "requirements_text": req,
        "education_required": extract_education(req or fields.get("education", "")),
        "min_years": extract_years(req),
        "employer": fields.get("employer") or fields.get("company") or "",
        "deadline": fields.get("deadline") or "",
        "contact": fields.get("contact") or "",
        "priority": priority,
        "raw_text": text,
    }
    return result


def vagueness(text_or_fields: dict | str) -> str:
    """Classify vacancy vagueness: 'ok' | 'vague_with_quals' | 'too_vague'.

    Vague WITH clear qualifications -> scrape by qualifications.
    Vague WITHOUT -> broad + label 'broad match — review'.
    Too vague (no title, no requirements) -> ask 1 clarifying question.
    """
    if isinstance(text_or_fields, str):
        parsed = parse_vacancy_text(text_or_fields)
    else:
        parsed = text_or_fields
    title = (parsed.get("title") or "").strip()
    req = (parsed.get("requirements_text") or "").strip()
    edu = (parsed.get("education_required") or "").strip()
    if not title and not req:
        return "too_vague"
    if len(req) < 15 and not edu and not parsed.get("min_years"):
        # Title only, e.g. "Need a driver" — broad scrape, labelled.
        return "vague_no_quals"
    if len(req) < 15 and edu:
        return "vague_with_quals"
    return "ok"
