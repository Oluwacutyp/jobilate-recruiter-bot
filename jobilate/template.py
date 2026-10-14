"""Fixed outreach template + interview helper.

The template stays FIXED — only the job opening details change.
The bot NEVER sends this template anywhere. It only shows it to the
recruiter so SHE can copy it and send it herself. This module has no
sending capability at all.
"""
from __future__ import annotations

FIXED_TEMPLATE = """Hello {name}, good day. This is {recruiter} from Jobilate Recruitment.

We saw your CV and think you may fit this opening:

Role: {role}
Location: {location}
Pay: {pay}
Type: {job_type}

Requirements: {requirements}

If you are interested, please reply with:
1. Your current location
2. Your availability to start
3. Confirmation that you meet the requirements above

Thank you.
— Jobilate Recruitment"""


def render_template(vacancy: dict, candidate_name: str = "", recruiter: str = "Jobilate Recruitment") -> str:
    return FIXED_TEMPLATE.format(
        name=candidate_name or "there",
        recruiter=recruiter,
        role=vacancy.get("title", ""),
        location=vacancy.get("location", ""),
        pay=vacancy.get("pay_text", ""),
        job_type=vacancy.get("job_type", "Full-Time"),
        requirements=vacancy.get("requirements_text", ""),
    )


def interview_checklist(vacancy: dict) -> str:
    req = vacancy.get("requirements_text", "")
    lines = [f"🧾 Interview checklist — {vacancy.get('title', '')}", ""]
    lines.append("Before the call:")
    lines.append("• Confirm current location + willingness to travel/relocate")
    lines.append("• Confirm availability / notice period")
    lines.append("• Confirm expected pay vs vacancy pay")
    lines.append("")
    lines.append("Ask about:")
    if req:
        lines.append(f"• Requirements from vacancy: {req}")
    lines.append("• Most recent role: what did you actually do day to day?")
    lines.append("• One real example of the core skill (sales numbers, farm accounts, team led)")
    lines.append("• Why did you leave / why are you looking?")
    lines.append("")
    lines.append("Red flags to note:")
    lines.append("• Vague answers on experience, gaps with no explanation, pay far above range")
    lines.append("")
    lines.append("After: mark the candidate in the bot (Interested / Not fit / No reply).")
    return "\n".join(lines)
