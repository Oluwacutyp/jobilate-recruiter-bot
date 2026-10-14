import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jobilate.dedup import normalize_phone, candidate_key, dedup_candidates


def test_normalize_nigerian_local():
    assert normalize_phone("08000000001") == "+2348000000001"


def test_normalize_keeps_plus():
    assert normalize_phone("+234 800 000 0001") == "+2348000000001"


def test_same_phone_same_key():
    assert candidate_key("Ada O.", "08000000001") == candidate_key("Ada O.", "+2348000000001")


def test_dedup_by_phone():
    cands = [
        {"name": "Ada O.", "phone": "08000000001", "title": "Sales Rep", "skills": ""},
        {"name": "Ada O.", "phone": "+2348000000001", "title": "Sales Rep", "skills": "vet sales"},
    ]
    out = dedup_candidates(cands)
    assert len(out) == 1
    assert out[0]["skills"] == "vet sales"  # merged from duplicate
