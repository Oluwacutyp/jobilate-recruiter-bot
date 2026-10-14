import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jobilate.vacancy_parser import parse_vacancy_text, parse_pay, vagueness
from jobilate.sample_cvs import SAMPLE_VACANCY_TEXT


def test_sample1_parses():
    p = parse_vacancy_text(SAMPLE_VACANCY_TEXT)
    assert p["title"] == "Sales Supervisor"
    assert "Lagos" in p["location"]
    assert p["pay_min"] == 500000
    assert p["min_years"] == 5
    assert "b.tech" in p["education_required"] or "b.sc" in p["education_required"]


def test_parse_pay():
    _, m = parse_pay("₦500,000+/month")
    assert m == 500000


def test_too_vague():
    assert vagueness("") == "too_vague"
    assert vagueness("Need someone") in ("vague_no_quals", "vague_with_quals", "ok")


def test_title_only_is_broad():
    assert vagueness({"title": "Driver", "requirements_text": "", "education_required": "", "min_years": None}) == "vague_no_quals"
