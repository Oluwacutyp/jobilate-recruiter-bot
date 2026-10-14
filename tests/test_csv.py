import sys, os, csv, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jobilate.csv_export import CSV_COLUMNS, write_csv, build_digest


def test_csv_roundtrip():
    links = [{"vacancy_id": 1, "candidate_id": 2, "name": "Sample Adaeze O.", "phone": "+0000000001",
              "ctitle": "Sales Supervisor", "cloc": "Lagos State", "highest_qualification": "B.Tech",
              "experience_years": 6, "expected_salary": "₦400,000", "skills": "vet sales",
              "cv_url": "https://jiji.ng/sample", "score": 90, "tier": "Tier1",
              "match_reason": "good", "mark": "Texted", "marked_at": "2026-10-14",
              "sent_by_her": 1, "sent_to_employer": 0, "harvested_to_her": 1}]
    path = os.path.join(tempfile.mkdtemp(), "out.csv")
    write_csv(path, links, "#1 Sales Supervisor")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == CSV_COLUMNS
    assert rows[0]["name"] == "Sample Adaeze O."
    assert rows[0]["tier"] == "Tier1"


def test_digest_readable():
    links = [{"name": "Sample Adaeze O.", "phone": "+0000000001", "ctitle": "Sales Rep",
              "cloc": "Lagos State", "tier": "Tier1", "match_reason": "good",
              "cv_url": "https://jiji.ng/sample"}]
    d = build_digest(links, "#1 Sales Supervisor")
    assert "Sample Adaeze O." in d and "+0000000001" in d
