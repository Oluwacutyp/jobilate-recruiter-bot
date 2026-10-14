"""SQLite store: vacancies / candidates / vacancy_links / marks.

Harvest flags live on vacancy_links: harvested_to_her, sent_by_her,
sent_to_employer. One candidate row, many links (cross-vacancy dedup).
"""
from __future__ import annotations

import os
import sqlite3

from .dedup import candidate_key, normalize_phone
from .models import Candidate, Vacancy, VacancyLink, utcnow_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, category TEXT DEFAULT '', location TEXT DEFAULT '',
  pay_text TEXT DEFAULT '', pay_min INTEGER, job_type TEXT DEFAULT 'Full-Time',
  requirements_text TEXT DEFAULT '', education_required TEXT DEFAULT '',
  min_years INTEGER, employer TEXT DEFAULT '', deadline TEXT DEFAULT '',
  contact TEXT DEFAULT '', priority TEXT DEFAULT 'Normal',
  status TEXT DEFAULT 'draft', live_push INTEGER DEFAULT 1,
  school_mode INTEGER DEFAULT 0, created_at TEXT, raw_text TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, phone TEXT, dedup_key TEXT UNIQUE, title TEXT DEFAULT '',
  job_type TEXT DEFAULT '', employment_status TEXT DEFAULT '',
  education TEXT DEFAULT '', highest_qualification TEXT DEFAULT '',
  skills TEXT DEFAULT '', languages TEXT DEFAULT '', certifications TEXT DEFAULT '',
  experience_text TEXT DEFAULT '', experience_years REAL,
  expected_salary TEXT DEFAULT '', expected_salary_min INTEGER,
  location TEXT DEFAULT '', cv_url TEXT DEFAULT '', source TEXT DEFAULT 'jiji',
  blocked INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS vacancy_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vacancy_id INTEGER NOT NULL, candidate_id INTEGER NOT NULL,
  score REAL DEFAULT 0, tier TEXT DEFAULT 'Tier3', match_reason TEXT DEFAULT '',
  mark TEXT DEFAULT '', marked_at TEXT DEFAULT '',
  sent_by_her INTEGER DEFAULT 0, sent_to_employer INTEGER DEFAULT 0,
  harvested_to_her INTEGER DEFAULT 0, created_at TEXT,
  UNIQUE(vacancy_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT DEFAULT ''
);
"""


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- settings ----
    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # ---- vacancies ----
    def add_vacancy(self, v: Vacancy) -> int:
        cur = self.conn.execute(
            "INSERT INTO vacancies(title,category,location,pay_text,pay_min,job_type,requirements_text,education_required,min_years,employer,deadline,contact,priority,status,live_push,school_mode,created_at,raw_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (v.title, v.category, v.location, v.pay_text, v.pay_min, v.job_type, v.requirements_text, v.education_required, v.min_years, v.employer, v.deadline, v.contact, v.priority, v.status, 1 if v.live_push else 0, 1 if v.school_mode else 0, v.created_at, v.raw_text))
        self.conn.commit()
        v.id = cur.lastrowid
        return v.id

    def get_vacancy(self, vid: int) -> Vacancy | None:
        row = self.conn.execute("SELECT * FROM vacancies WHERE id=?", (vid,)).fetchone()
        return _row_to_vacancy(row) if row else None

    def list_vacancies(self, status: str | None = None) -> list[Vacancy]:
        q = "SELECT * FROM vacancies ORDER BY id DESC"
        rows = self.conn.execute(q).fetchall() if not status else self.conn.execute("SELECT * FROM vacancies WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        return [_row_to_vacancy(r) for r in rows]

    def update_vacancy(self, vid: int, **fields) -> bool:
        allowed = {"title", "category", "location", "pay_text", "pay_min", "job_type", "requirements_text", "education_required", "min_years", "employer", "deadline", "contact", "priority", "status", "live_push", "school_mode"}
        sets, vals = [], []
        for k, val in fields.items():
            if k in allowed:
                sets.append(f"{k}=?")
                vals.append(1 if val is True else 0 if val is False else val)
        if not sets:
            return False
        vals.append(vid)
        cur = self.conn.execute(f"UPDATE vacancies SET {', '.join(sets)} WHERE id=?", vals)
        self.conn.commit()
        return cur.rowcount > 0

    def delete_vacancy(self, vid: int) -> bool:
        self.conn.execute("DELETE FROM vacancy_links WHERE vacancy_id=?", (vid,))
        cur = self.conn.execute("DELETE FROM vacancies WHERE id=?", (vid,))
        self.conn.commit()
        return cur.rowcount > 0

    # ---- candidates ----
    def add_or_get_candidate(self, c: Candidate) -> int:
        key = candidate_key(c.name, c.phone, c.title)
        row = self.conn.execute("SELECT id FROM candidates WHERE dedup_key=?", (key,)).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO candidates(name,phone,dedup_key,title,job_type,employment_status,education,highest_qualification,skills,languages,certifications,experience_text,experience_years,expected_salary,expected_salary_min,location,cv_url,source,blocked,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c.name, normalize_phone(c.phone), key, c.title, c.job_type, c.employment_status, c.education, c.highest_qualification, c.skills, c.languages, c.certifications, c.experience_text, c.experience_years, c.expected_salary, c.expected_salary_min, c.location, c.cv_url, c.source, 1 if c.blocked else 0, c.created_at))
        self.conn.commit()
        c.id = cur.lastrowid
        return c.id

    def get_candidate(self, cid: int) -> Candidate | None:
        row = self.conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
        return _row_to_candidate(row) if row else None

    def set_blocked(self, cid: int, blocked: bool) -> bool:
        cur = self.conn.execute("UPDATE candidates SET blocked=? WHERE id=?", (1 if blocked else 0, cid))
        self.conn.commit()
        return cur.rowcount > 0

    # ---- links / marks ----
    def link_candidate(self, vacancy_id: int, candidate_id: int, score: float, tier: str, reason: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO vacancy_links(vacancy_id,candidate_id,score,tier,match_reason,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(vacancy_id,candidate_id) DO UPDATE SET score=excluded.score, tier=excluded.tier, match_reason=excluded.match_reason",
            (vacancy_id, candidate_id, score, tier, reason, utcnow_iso()))
        self.conn.commit()
        row = self.conn.execute("SELECT id FROM vacancy_links WHERE vacancy_id=? AND candidate_id=?", (vacancy_id, candidate_id)).fetchone()
        return row["id"]

    def set_mark(self, vacancy_id: int, candidate_id: int, mark: str) -> bool:
        extra = ""
        vals: list = [mark, utcnow_iso()]
        if mark == "Texted":
            extra = ", sent_by_her=1"
        if mark == "Sent to employer":
            extra = ", sent_to_employer=1, sent_by_her=1"
        cur = self.conn.execute(f"UPDATE vacancy_links SET mark=?, marked_at=?{extra} WHERE vacancy_id=? AND candidate_id=?", (*vals, vacancy_id, candidate_id))
        self.conn.commit()
        return cur.rowcount > 0

    def mark_harvested(self, link_ids: list[int]) -> None:
        for lid in link_ids:
            self.conn.execute("UPDATE vacancy_links SET harvested_to_her=1 WHERE id=?", (lid,))
        self.conn.commit()

    def links_for_vacancy(self, vacancy_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT l.*, c.name, c.phone, c.title AS ctitle, c.location AS cloc, c.cv_url, c.expected_salary, c.highest_qualification, c.experience_years FROM vacancy_links l JOIN candidates c ON c.id=l.candidate_id WHERE l.vacancy_id=? ORDER BY l.score DESC, l.id ASC",
            (vacancy_id,)).fetchall()
        return [dict(r) for r in rows]

    def all_links(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT l.*, c.name, c.phone, c.title AS ctitle, c.location AS cloc, c.cv_url FROM vacancy_links l JOIN candidates c ON c.id=l.candidate_id ORDER BY l.id ASC").fetchall()
        return [dict(r) for r in rows]

    def other_vacancies_for_candidate(self, candidate_id: int, exclude_vacancy: int) -> list[Vacancy]:
        rows = self.conn.execute(
            "SELECT v.* FROM vacancy_links l JOIN vacancies v ON v.id=l.vacancy_id WHERE l.candidate_id=? AND l.vacancy_id!=?",
            (candidate_id, exclude_vacancy)).fetchall()
        return [_row_to_vacancy(r) for r in rows]

    def stats_for_vacancy(self, vacancy_id: int) -> dict:
        links = self.links_for_vacancy(vacancy_id)
        out: dict[str, int] = {"total": len(links), "Tier1": 0, "Tier2": 0, "Tier3": 0}
        for ln in links:
            out[ln["tier"]] = out.get(ln["tier"], 0) + 1
            if ln["mark"]:
                out["mark:" + ln["mark"]] = out.get("mark:" + ln["mark"], 0) + 1
        return out


def _row_to_vacancy(r: sqlite3.Row) -> Vacancy:
    return Vacancy(id=r["id"], title=r["title"], category=r["category"], location=r["location"], pay_text=r["pay_text"], pay_min=r["pay_min"], job_type=r["job_type"], requirements_text=r["requirements_text"], education_required=r["education_required"], min_years=r["min_years"], employer=r["employer"], deadline=r["deadline"], contact=r["contact"], priority=r["priority"], status=r["status"], live_push=bool(r["live_push"]), school_mode=bool(r["school_mode"]), created_at=r["created_at"], raw_text=r["raw_text"])


def _row_to_candidate(r: sqlite3.Row) -> Candidate:
    return Candidate(id=r["id"], name=r["name"], phone=r["phone"], title=r["title"], job_type=r["job_type"], employment_status=r["employment_status"], education=r["education"], highest_qualification=r["highest_qualification"], skills=r["skills"], languages=r["languages"], certifications=r["certifications"], experience_text=r["experience_text"], experience_years=r["experience_years"], expected_salary=r["expected_salary"], expected_salary_min=r["expected_salary_min"], location=r["location"], cv_url=r["cv_url"], source=r["source"], blocked=bool(r["blocked"]), created_at=r["created_at"])
