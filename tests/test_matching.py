import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jobilate.matching import score_candidate, expand_roles, categories_for_title
from jobilate.vacancy_parser import parse_vacancy_text
from jobilate.sample_cvs import SAMPLE_CVS, SAMPLE_VACANCY_TEXT


def _vac():
    return parse_vacancy_text(SAMPLE_VACANCY_TEXT)


def test_sample1_tier1_first():
    score, tier, reason = score_candidate(_vac(), SAMPLE_CVS[0])
    assert tier == "Tier1", reason
    assert score >= 70


def test_sample1_second_is_tier1_or_2():
    _, tier, _ = score_candidate(_vac(), SAMPLE_CVS[1])
    assert tier in ("Tier1", "Tier2")


def test_vague_cv_still_included_as_tier3():
    score, tier, _ = score_candidate(_vac(), SAMPLE_CVS[3])
    assert tier == "Tier3"
    assert score >= 0


def test_lower_expected_salary_not_disqualifying():
    _, tier, reason = score_candidate(_vac(), SAMPLE_CVS[0])
    assert "not a blocker" in reason


def test_cross_category_sales_supervisor():
    cats = categories_for_title("Sales Supervisor")
    assert "Farming & Veterinary" in cats or "farming & veterinary" in [c.lower() for c in cats]


def test_expand_roles():
    assert "sales manager" in expand_roles("Sales Supervisor") or len(expand_roles("Sales Supervisor")) > 1
