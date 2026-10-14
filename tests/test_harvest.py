import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jobilate.store import Store
from jobilate.models import Vacancy, Candidate
from jobilate.harvest import harvest


def _store():
    tmp = tempfile.mkdtemp()
    return Store(os.path.join(tmp, "t.db"))


def _seed(s):
    vid = s.add_vacancy(Vacancy(title="Sales Supervisor", location="Lagos State", status="active"))
    c1 = s.add_or_get_candidate(Candidate(name="A", phone="+0000000011", title="Sales Rep"))
    c2 = s.add_or_get_candidate(Candidate(name="B", phone="+0000000012", title="Sales Rep"))
    s.link_candidate(vid, c1, 90, "Tier1", "good")
    s.link_candidate(vid, c2, 40, "Tier3", "broad")
    return vid, c1, c2


def test_incremental_only_unharvested_then_marks():
    s = _store()
    vid, _, _ = _seed(s)
    picked, _ = harvest(s, vid, "incremental")
    assert len(picked) == 2
    picked2, _ = harvest(s, vid, "incremental")
    assert picked2 == []


def test_unsent_filters():
    s = _store()
    vid, c1, _ = _seed(s)
    s.set_mark(vid, c1, "Texted")
    picked, _ = harvest(s, vid, "unsent")
    assert len(picked) == 1
    assert picked[0]["candidate_id"] != c1


def test_unsent_employer_filters():
    s = _store()
    vid, c1, _ = _seed(s)
    s.set_mark(vid, c1, "Sent to employer")
    picked, _ = harvest(s, vid, "unsent_employer")
    assert len(picked) == 1


def test_dump_returns_all():
    s = _store()
    vid, _, _ = _seed(s)
    harvest(s, vid, "incremental")
    picked, _ = harvest(s, vid, "all")
    assert len(picked) == 2
