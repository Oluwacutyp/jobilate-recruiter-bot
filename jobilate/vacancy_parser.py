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

LABEL_RE = re.compile(r"^\s*(job vacancy|vacancy|role|title|position|location|pay|salary|job type|employment type|employment|industry|requirements?|education|experience|employer|company|deadline|contact|priority)\s*[:\-–]\s*(.+)$", re.I)
PAY_RE = re.compile(r"(\d[\d,]*)\s*(?:\+|and\s+above|above|per\s+month|/month|monthly)?", re.I)
YEARS_RE = re.compile(r"(\d+)\s*\+\s*(?:years?|yrs?)", re.I)
# ADDITIVE: section headers with no value on the line, e.g. "Requirements:" / "Key Responsibilities:".
SECTION_HEADER_RE = re.compile(r"^\s*(requirements?|key responsibilities|responsibilities|duties)\s*:?\s*$", re.I)
BULLET_RE = re.compile(r"^\s*[\*\•\-\–—]\s+(.+)$")
VACANCY_PREFIX_RE = re.compile(r"^(job\s+vacancy|vacancy)\s*[:\-–]\s*(.+)$", re.I)
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
    # "5 years of experience" / "5 years' verifiable experience" — words
    # may sit between the years and "experience".
    m2 = re.search(r"(\d+)\s*(?:years?|yrs?)\s*(?:['’]\s*)?(?:of\s+)?(?:\w+\s+){0,3}?(?:experience|exp)\b", (text or ""), re.I)
    if m2:
        return int(m2.group(1))
    # Fallback: bare "5 years" in requirements almost always means experience.
    m3 = re.search(r"(\d+)\s*(?:years?|yrs?)\b", text or "", re.I)
    return int(m3.group(1)) if m3 else None


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


def _title_case_if_shouting(title: str) -> str:
    """"SALES SUPERVISOR" -> "Sales Supervisor". Leaves mixed case alone."""
    title = (title or "").strip()
    if title and title.isupper():
        return title.title()
    return title


def parse_vacancy_text(text: str) -> dict:
    """Parse vacancy text into a field dict. Never raises on junk input.

    ADDITIVE (2026-10-14): also handles her real pasted format —
    "JOB VACANCY: SALES SUPERVISOR", "Industry:", "Employment Type:",
    bullet lines ("* ..."), "Requirements:" / "Key Responsibilities:"
    headers with the items on following lines, and "5 years" without "+".
    Existing labelled formats keep working exactly as before.
    """
    text = (text or "").strip()
    fields: dict[str, str] = {}
    req_parts: list[str] = []
    in_req_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # "JOB VACANCY: SALES SUPERVISOR" -> title (handled via LABEL_RE too,
        # but keep the prefix out of requirements).
        vm = VACANCY_PREFIX_RE.match(line)
        if vm and not fields.get("job vacancy"):
            fields["job vacancy"] = vm.group(2).strip()
            continue
        # Section headers ("Requirements:", "Key Responsibilities:") open
        # the requirements section; the items live on following lines.
        if SECTION_HEADER_RE.match(line):
            in_req_section = True
            continue
        # Bullet lines: strip the bullet, then treat as a requirements item
        # when in a requirements section, else parse as a labelled line.
        bullet = BULLET_RE.match(line)
        cleaned = bullet.group(1).strip() if bullet else line
        m = LABEL_RE.match(cleaned)
        if m:
            key = m.group(1).lower().replace("requirements", "requirements")
            fields[key] = m.group(2).strip()
            # A labelled Requirements/Education/Experience line is also a
            # requirements item (e.g. "* Education (Mandatory): B.Tech...").
            if key in ("requirements", "requirement", "education", "experience"):
                req_parts.append(m.group(2).strip())
            in_req_section = False
            continue
        if in_req_section or bullet:
            req_parts.append(cleaned)
            continue
    title = (
        fields.get("role")
        or fields.get("title")
        or fields.get("position")
        or fields.get("job vacancy")
        or fields.get("vacancy")
        or ""
    )
    title = _title_case_if_shouting(title)
    if not title:
        for line in text.splitlines():
            if line.strip():
                title = _title_case_if_shouting(line.strip()[:120])
                break
    # Defensive (2026-10-14): title MUST be a single line, max 120 chars.
    # A pasted vacancy must never become the title (that once produced a
    # multi-KB title -> giant search URL -> giant error bubble).
    title = (title.splitlines()[0].strip() if title.strip() else "")[:120]
    location = fields.get("location") or guess_location(text)
    pay_raw = fields.get("pay") or fields.get("salary") or ""
    pay_text, pay_min = parse_pay(pay_raw or text) if pay_raw else ("", None)
    req = fields.get("requirement") or fields.get("requirements") or ""
    if req_parts:
        req = " ".join(req_parts) if not req else req + " " + " ".join(req_parts)
    if not req:
        # Everything after the title line is requirements when unlabelled.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        req = " ".join(lines[1:]) if len(lines) > 1 else ""
    job_type = fields.get("job type") or fields.get("employment type") or fields.get("employment") or "Full-Time"
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
        "employer": fields.get("employer") or fields.get("company") or fields.get("industry") or "",
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
