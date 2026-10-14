"""CV files + ZIP delivery tests (placeholder data only — no real contacts)."""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobilate.cv_files import (
    MAX_ZIP_BYTES,
    build_harvest_zip,
    cv_entries_for_links,
    cv_filename,
    cv_text_for_link,
    safe_filename_component,
    zip_exceeds_cap,
)

LINK = {
    "candidate_id": 7,
    "name": "Sample Adaeze O.",
    "phone": "+0000000001",
    "ctitle": "Sales Supervisor",
    "cloc": "Lagos State",
    "highest_qualification": "B.Tech",
    "experience_years": 6,
    "experience_text": "6 years vet drug sales",
    "skills": "vet sales, team lead",
    "languages": "English",
    "certifications": "None",
    "expected_salary": "400000",
    "cv_url": "https://example.test/cv/7",
    "score": 90,
    "tier": "Tier1",
    "match_reason": "education + 6y + domain fit",
    "mark": "Texted",
    "vacancy_id": 1,
}


def test_cv_text_contains_key_fields():
    text = cv_text_for_link(LINK)
    assert "Sample Adaeze O." in text
    assert "+0000000001" in text
    assert "education + 6y + domain fit" in text
    assert "https://example.test/cv/7" in text
    assert "B.Tech" in text
    assert "vet sales" in text
    assert "Tier1" in text


def test_filename_sanitization_no_slashes_or_traversal():
    evil = dict(LINK, name="../../etc/passwd", candidate_id=9)
    fname = cv_filename(evil)
    assert "/" not in fname and "\\" not in fname
    assert ".." not in fname
    assert fname.startswith("cv_9_") and fname.endswith(".txt")
    assert safe_filename_component("A/B C:D") == "A_B_C_D"
    assert safe_filename_component("") == "candidate"


def test_zip_contains_csv_cvs_readme_and_opens():
    links = [LINK, dict(LINK, candidate_id=8, name="Sample Bello K.", phone="+0000000002")]
    data = build_harvest_zip(links, csv_bytes=b"a,b\n1,2\n", csv_filename="harvest_all.csv", vacancy_label="#1 Sales Supervisor")
    assert len(data) > 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "harvest_all.csv" in names
        assert "README.txt" in names
        assert "cv_7_Sample_Adaeze_O.txt" in names
        assert "cv_8_Sample_Bello_K.txt" in names
        assert "How to unzip" in zf.read("README.txt").decode("utf-8")
        assert "Sample Adaeze O." in zf.read("cv_7_Sample_Adaeze_O.txt").decode("utf-8")


def test_zip_empty_list_does_not_crash():
    data = build_harvest_zip([], csv_bytes=b"a,b\n", csv_filename="empty.csv", vacancy_label="Empty")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert "README.txt" in zf.namelist()
        assert "empty.csv" in zf.namelist()


def test_zip_cap_logic():
    assert not zip_exceeds_cap(100)
    assert not zip_exceeds_cap(MAX_ZIP_BYTES)
    assert zip_exceeds_cap(MAX_ZIP_BYTES + 1)


def test_cv_entries_dedupe_same_candidate_across_vacancies():
    links = [LINK, dict(LINK, vacancy_id=2, match_reason="also matches other vacancy")]
    entries = cv_entries_for_links(links)
    assert len(entries) == 1
    assert entries[0][0] == "cv_7_Sample_Adaeze_O.txt"
