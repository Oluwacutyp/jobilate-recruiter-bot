"""Data models — plain dataclasses, no ORM."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

MARK_VALUES = ("Texted", "Interested", "No reply", "Not fit", "Sent to employer")
VACANCY_STATUSES = ("draft", "active", "paused", "stopped", "closed")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Vacancy:
    id: int | None = None
    title: str = ""
    category: str = ""
    location: str = ""
    pay_text: str = ""
    pay_min: int | None = None
    job_type: str = "Full-Time"
    requirements_text: str = ""
    education_required: str = ""
    min_years: int | None = None
    employer: str = ""
    deadline: str = ""
    contact: str = ""
    priority: str = "Normal"  # High | Normal
    status: str = "draft"
    live_push: bool = True
    school_mode: bool = False
    created_at: str = field(default_factory=utcnow_iso)
    raw_text: str = ""

    def label(self) -> str:
        return f"#{self.id} {self.title}" if self.id else self.title


@dataclass
class Candidate:
    id: int | None = None
    name: str = ""
    phone: str = ""
    title: str = ""
    job_type: str = ""
    employment_status: str = ""
    education: str = ""
    highest_qualification: str = ""
    skills: str = ""
    languages: str = ""
    certifications: str = ""
    experience_text: str = ""
    experience_years: float | None = None
    expected_salary: str = ""
    expected_salary_min: int | None = None
    location: str = ""
    cv_url: str = ""
    source: str = "jiji"
    blocked: bool = False
    created_at: str = field(default_factory=utcnow_iso)


@dataclass
class VacancyLink:
    id: int | None = None
    vacancy_id: int = 0
    candidate_id: int = 0
    score: float = 0.0
    tier: str = "Tier3"
    match_reason: str = ""
    mark: str = ""
    marked_at: str = ""
    sent_by_her: bool = False
    sent_to_employer: bool = False
    harvested_to_her: bool = False
    created_at: str = field(default_factory=utcnow_iso)
