import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jobilate.store import Store
from jobilate.models import Vacancy, Candidate


def _store():
    return Store(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_vacancy_crud_and_status():
    s = _store()
    vid = s.add_vacancy(Vacancy(title="Driver", location="Lagos", status="draft"))
    assert s.get_vacancy(vid).title == "Driver"
    s.update_vacancy(vid, status="active")
    assert s.get_vacancy(vid).status == "active"
    assert s.delete_vacancy(vid) is True
    assert s.get_vacancy(vid) is None


def test_cross_vacancy_dedup_one_candidate_two_links():
    s = _store()
    v1 = s.add_vacancy(Vacancy(title="Sales Supervisor", status="active"))
    v2 = s.add_vacancy(Vacancy(title="Sales Rep", status="active"))
    cid = s.add_or_get_candidate(Candidate(name="Sample Adaeze O.", phone="08000000001", title="Sales Rep"))
    cid2 = s.add_or_get_candidate(Candidate(name="Sample Adaeze O.", phone="+2348000000001", title="Sales Rep"))
    assert cid == cid2
    s.link_candidate(v1, cid, 90, "Tier1", "good")
    s.link_candidate(v2, cid, 70, "Tier2", "also good")
    assert len(s.other_vacancies_for_candidate(cid, v1)) == 1
    assert len(s.links_for_vacancy(v1)) == 1


def test_mark_feeds_flags():
    s = _store()
    vid = s.add_vacancy(Vacancy(title="Driver", status="active"))
    cid = s.add_or_get_candidate(Candidate(name="A", phone="+0000000099", title="Driver"))
    s.link_candidate(vid, cid, 50, "Tier2", "ok")
    assert s.set_mark(vid, cid, "Texted") is True
    assert s.set_mark(vid, cid, "Sent to employer") is True
    ln = s.links_for_vacancy(vid)[0]
    assert ln["sent_by_her"] == 1 and ln["sent_to_employer"] == 1


def test_pause_one_does_not_affect_other():
    s = _store()
    v1 = s.add_vacancy(Vacancy(title="A", status="active"))
    v2 = s.add_vacancy(Vacancy(title="B", status="active"))
    s.update_vacancy(v1, status="paused")
    assert s.get_vacancy(v1).status == "paused"
    assert s.get_vacancy(v2).status == "active"
