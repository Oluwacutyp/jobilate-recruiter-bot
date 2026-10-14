"""Matching: category-first, synonym expansion, structured-field scoring.

Tiers (locked spec):
  Tier1 = education + 5y + domain fit
  Tier2 = one side strong (education OR experience/domain)
  Tier3 = vague / unknown — still included, after Tier1/2.
Expected salary LOWER than vacancy pay does NOT disqualify.
"""
from __future__ import annotations

import re

# Category -> roles it covers. Category-level first: Housekeeping covers
# cleaner / housekeeper / nanny / maid / steward, etc.
CATEGORY_ROLES: dict[str, list[str]] = {
    "housekeeping": ["cleaner", "housekeeper", "nanny", "maid", "steward", "house help", "domestic"],
    "sales": ["sales supervisor", "sales representative", "sales rep", "sales executive", "sales officer", "sales agent", "marketer", "telemarketing", "telesales"],
    "farming & veterinary": ["veterinary", "animal health", "animal production", "farm manager", "farm supervisor", "agric", "livestock", "poultry"],
    "advertising & marketing": ["marketing", "advertising", "brand", "promotion", "digital marketing"],
    "driving": ["driver", "chauffeur", "dispatch rider", "rider"],
    "security": ["security", "guard", "bouncer"],
    "cooking": ["cook", "chef", "caterer", "kitchen"],
    "teaching": ["teacher", "tutor", "lecturer", "instructor"],
    "accounting": ["accountant", "bookkeeper", "cashier", "audit"],
    "it": ["developer", "programmer", "it support", "technician", "data entry"],
    "admin": ["admin", "secretary", "receptionist", "office assistant", "personal assistant"],
    "healthcare": ["nurse", "pharmacist", "pharmacy", "lab scientist", "caregiver"],
    "engineering": ["engineer", "electrician", "plumber", "welder", "mechanic"],
}

# Synonym / related-role expansion (bidirectional lookup built below).
SYNONYMS: dict[str, list[str]] = {
    "sales supervisor": ["sales lead", "sales manager", "sales coordinator", "team lead sales"],
    "cleaner": ["housekeeper", "maid", "janitor"],
    "housekeeper": ["cleaner", "maid"],
    "nanny": ["childminder", "babysitter", "housekeeper"],
    "driver": ["chauffeur"],
    "marketer": ["sales representative", "sales rep", "telemarketer"],
    "farm manager": ["farm supervisor", "livestock manager"],
    "veterinary": ["vet", "animal health"],
    "accountant": ["bookkeeper"],
    "teacher": ["tutor"],
    "cook": ["chef"],
    "security": ["guard"],
}

# Senior roles pull CVs from several categories (cross-category).
CROSS_CATEGORY: dict[str, list[str]] = {
    "sales supervisor": ["farming & veterinary", "sales", "advertising & marketing"],
    "sales manager": ["farming & veterinary", "sales", "advertising & marketing"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def expand_roles(title: str) -> list[str]:
    """Expand a vacancy title to related roles + synonyms (deduped, ordered)."""
    base = _norm(title)
    out: list[str] = [base]
    for key, syns in SYNONYMS.items():
        if key in base or base in key:
            out.extend(syns)
    for cat, roles in CATEGORY_ROLES.items():
        if cat in base:
            out.extend(roles)
        for r in roles:
            if r in base and r not in out:
                out.append(r)
    seen, ded = set(), []
    for r in out:
        if r and r not in seen:
            seen.add(r)
            ded.append(r)
    return ded


def categories_for_title(title: str) -> list[str]:
    """Categories to scrape for a title (cross-category for senior roles)."""
    base = _norm(title)
    for key, cats in CROSS_CATEGORY.items():
        if key in base:
            return list(cats)
    found: list[str] = []
    for cat, roles in CATEGORY_ROLES.items():
        if cat in base or any(r in base for r in roles):
            found.append(cat)
    return found or ["sales", "admin"]


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _norm(s)) if len(t) > 2}


def score_candidate(vacancy: dict, cand: dict) -> tuple[float, str, str]:
    """Score 0-100 + tier + human-readable match reason.

    vacancy / cand are plain dicts (see models / sample_cvs).
    Broad recall: nothing is hard-rejected except blocked candidates
    (handled in store) — weak matches land in Tier3, still delivered.
    """
    reasons: list[str] = []
    score = 0.0
    v_title = _norm(vacancy.get("title", ""))
    c_title = _norm(cand.get("title", ""))
    c_text = " ".join(str(cand.get(k, "")) for k in ("title", "skills", "experience_text", "education", "highest_qualification", "certifications")).lower()
    v_req = (vacancy.get("requirements_text", "") or "").lower()
    v_edu = (vacancy.get("education_required", "") or "").lower()

    # --- Role / domain fit (max 40) ---
    expanded = expand_roles(vacancy.get("title", ""))
    role_hit = any(_norm(r) in c_title or _norm(r) in c_text for r in expanded)
    if role_hit:
        score += 30
        reasons.append(f"role fit: '{cand.get('title', '')}' matches '{vacancy.get('title', '')}' family")
    elif _tokens(v_title) & _tokens(c_title):
        score += 15
        reasons.append("partial role overlap")
    else:
        reasons.append("role not an exact match — broad recall")

    # Domain keywords from requirements (vet drugs, feed millers, farms…)
    domain_words = [w for w in ("vet", "veterinary", "animal", "agro", "pharma", "feed", "farm", "sales", "team", "travel", "distributor", "dealer") if w in v_req]
    domain_hits = [w for w in domain_words if w in c_text]
    if domain_hits:
        score += min(10, 3 * len(domain_hits))
        reasons.append("domain keywords: " + ", ".join(domain_hits))

    # --- Education (max 25) ---
    edu_strong = False
    c_edu = (str(cand.get("highest_qualification", "")) + " " + str(cand.get("education", ""))).lower()
    if v_edu:
        edu_tokens = [t for t in re.split(r"[, ]+", v_edu) if t]
        hits = [t for t in edu_tokens if t in c_edu]
        if hits:
            score += 25
            edu_strong = True
            reasons.append("education match: " + ", ".join(sorted(set(hits))))
        elif c_edu.strip():
            score += 5
            reasons.append("education present but not the requested one")
        else:
            reasons.append("education unknown")
    else:
        if c_edu.strip():
            score += 10
            edu_strong = True
            reasons.append("has stated qualifications")

    # --- Experience (max 25) ---
    exp = cand.get("experience_years")
    min_years = vacancy.get("min_years")
    exp_strong = False
    if isinstance(exp, (int, float)):
        if min_years and exp >= min_years:
            score += 25
            exp_strong = True
            reasons.append(f"experience {exp:g}y meets {min_years}y+")
        elif min_years and exp >= min_years - 2:
            score += 15
            reasons.append(f"experience {exp:g}y close to {min_years}y+")
        elif exp >= 3:
            score += 10
            reasons.append(f"experience {exp:g}y")
        elif exp > 0:
            score += 5
            reasons.append(f"experience {exp:g}y (junior)")
    else:
        reasons.append("experience years unknown")

    # --- Location (max 10) ---
    v_loc = _norm(vacancy.get("location", ""))
    c_loc = _norm(cand.get("location", ""))
    if v_loc and c_loc:
        if v_loc in c_loc or c_loc in v_loc:
            score += 10
            reasons.append(f"location match: {cand.get('location', '')}")
        else:
            score += 3
            reasons.append(f"location differs ({cand.get('location', '')} vs {vacancy.get('location', '')}) — tolerance applied")
    elif c_loc:
        score += 3
        reasons.append("location stated, vacancy location broad")

    # --- Salary: lower expected salary NEVER disqualifies (locked rule) ---
    exp_sal = cand.get("expected_salary_min")
    pay_min = vacancy.get("pay_min")
    if isinstance(exp_sal, (int, float)) and isinstance(pay_min, (int, float)):
        if exp_sal <= pay_min:
            reasons.append("expected salary at/below vacancy pay — not a blocker")
        else:
            score -= 5
            reasons.append("expected salary above vacancy pay — still included")

    score = max(0.0, min(100.0, score))
    # --- Tier assignment ---
    if edu_strong and exp_strong and role_hit:
        tier = "Tier1"
    elif (edu_strong or exp_strong) and (role_hit or domain_hits):
        tier = "Tier2"
    elif score >= 55:
        tier = "Tier2"
    else:
        tier = "Tier3"
    if not reasons:
        reasons.append("broad match — review")
    return score, tier, "; ".join(reasons)
