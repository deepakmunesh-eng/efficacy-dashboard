"""
Pull classroom review submissions from the Vercel admin JSON API
(/api/admin/submissions?key=…). Returns records normalised to the schema the
scoring engine expects (learning_q1..q5, practice_q7..q9, overall_effectiveness).
"""
from __future__ import annotations

import requests

from config.settings import CLASSROOM_ADMIN_URL, CLASSROOM_ADMIN_KEY

# Raw submission field → our normalised field.
_FIELD_MAP = {
    "lesson_activity_reference": "activity_ref",
    "chapter_name":             "chapter",
    "lesson_name":              "lesson",
    "grade":                    "grade",
    "teacher_name":             "teacher_name",
    "student_name":             "student_name",
    "class_date":               "class_date",
    "class_time":               "class_time",
    "q1_answer":                "learning_q1",
    "q2_answer":                "learning_q2",
    "q3_answer":                "learning_q3",
    "q4_answer":                "learning_q4",
    "q5_answer":                "learning_q5",
    "q6_long_answer":           "learning_notes",
    "q7_answer":                "practice_q7",
    "q8_answer":                "practice_q8",
    "q9_answer":                "practice_q9",
    "q10_long_answer":          "practice_notes",
    "q11_rating":               "overall_effectiveness",
    "q12_long_answer":          "specific_instances",
}


def _normalise_record(raw: dict) -> dict:
    out = {dst: str(raw.get(src, "") or "").strip() for src, dst in _FIELD_MAP.items()}
    return out


def fetch_classroom_reviews() -> list[dict]:
    """Fetch all classroom submissions from the admin JSON API."""
    try:
        resp = requests.get(
            CLASSROOM_ADMIN_URL,
            params={"key": CLASSROOM_ADMIN_KEY},
            timeout=25,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[classroom_reader] Could not reach admin API: {exc}")
        return []

    if isinstance(data, dict):
        raw_records = (data.get("submissions") or data.get("data")
                       or data.get("reviews") or data.get("results") or [])
    elif isinstance(data, list):
        raw_records = data
    else:
        raw_records = []

    records = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        rec = _normalise_record(raw)
        if rec.get("activity_ref") or rec.get("lesson"):
            records.append(rec)
    return records


def group_classroom_by_lesson(records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for r in records:
        key = r.get("activity_ref", "").strip()
        if key:
            grouped.setdefault(key, []).append(r)
    return grouped
