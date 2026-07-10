"""Collect the concrete errors flagged for a lesson — from the Errors Reported
tab AND from any free-response box (item detail notes, practice/exit
observations, additional suggestions). Used for the program-level Errors
Reported tracker (grade → chapter, mark-as-fixed)."""
from __future__ import annotations

import hashlib

from processing.scoring import classify_error

# Free-response fields scanned for errors, with a human label.
_FREE_FIELDS = [
    ("understanding_details",     "Understanding notes"),
    ("examples_practice_details", "Examples notes"),
    ("engagement_details",        "Engagement notes"),
    ("practice_observations",     "Practice observations"),
    ("exit_ticket_observations",  "Exit-ticket observations"),
    ("additional_suggestions",    "Additional suggestions"),
]


def _eid(*parts: str) -> str:
    return hashlib.sha256("|".join(p or "" for p in parts).encode()).hexdigest()[:16]


def collect_lesson_errors(activity_ref: str, grade: str, chapter: str, lesson: str,
                          lesson_rows: list[dict], error_reports: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    # 1. Errors Reported tab (structured, concrete).
    for e in (error_reports or []):
        text  = (e.get("error_details") or "").strip()
        etype = (e.get("error_type") or "").strip()
        pen, sev = classify_error(etype, text)
        sev = sev or "moderate"          # a reported error is a real defect
        eid = _eid(activity_ref, e.get("item_ref", ""), "reported", text[:80])
        if eid in seen:
            continue
        seen.add(eid)
        out.append({
            "id": eid, "grade": grade, "chapter": chapter, "lesson": lesson,
            "activity_ref": activity_ref, "item_ref": e.get("item_ref", ""),
            "source": "Errors Reported", "error_type": etype or sev.title(),
            "text": text, "reviewer": e.get("reviewer_name", ""), "severity": sev,
        })

    # 2. Any free-response box that contains an error signal.
    for r in (lesson_rows or []):
        rev  = (r.get("reviewer_name") or "").strip()
        item = (r.get("item_ref") or "").strip()
        for field, label in _FREE_FIELDS:
            text = (r.get(field) or "").strip()
            if not text:
                continue
            pen, sev = classify_error(text)
            if pen == 0.0:
                continue
            eid = _eid(activity_ref, item, field, text[:80])
            if eid in seen:
                continue
            seen.add(eid)
            out.append({
                "id": eid, "grade": grade, "chapter": chapter, "lesson": lesson,
                "activity_ref": activity_ref, "item_ref": item,
                "source": label, "error_type": sev.title(),
                "text": text, "reviewer": rev, "severity": sev,
            })
    return out
