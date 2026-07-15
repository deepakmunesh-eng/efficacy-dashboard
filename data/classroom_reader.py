"""
Pull classroom review submissions from the Vercel admin JSON API
(/api/admin/submissions?key=…). Returns records normalised to the schema the
scoring engine expects (learning_q1..q5, practice_q7..q9, overall_effectiveness).
"""
from __future__ import annotations

import re

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


def _ref_core(ref: str) -> str:
    """Normalise an activity ref to a comparable lesson-name core so the two
    naming schemes match: the coded 'US-G3-Find-the-Squares-...-V3-1.W03' and
    the human 'Find the Squares of Numbers up to 20.W01-V3.1' both reduce to
    'findthesquaresofnumbersupto20'. Drops the US/grade prefix, the version tail
    (from 'v3' on) and any trailing week token."""
    s = re.sub(r"[^a-z0-9]", "", (ref or "").lower())
    s = re.sub(r"^us", "", s)
    s = re.sub(r"^g\d+", "", s)          # grade token, e.g. g3
    m = re.search(r"v3", s)               # cut at the version marker
    if m:
        s = s[: m.start()]
    s = re.sub(r"w\d+$", "", s)           # trailing week token, e.g. w01
    return s


def match_classroom_to_lessons(records: list[dict],
                               lesson_refs) -> dict[str, list[dict]]:
    """Map classroom records onto sheet lesson activity_refs — exact match first,
    then a normalised-core fallback (handles the two ref naming schemes). Keyed
    by the SHEET activity_ref so it lines up with the scoring pipeline."""
    lesson_refs = list(lesson_refs)
    exact = set(lesson_refs)
    by_core: dict[str, str] = {}
    for lr in lesson_refs:
        by_core.setdefault(_ref_core(lr), lr)   # first wins on core collision

    out: dict[str, list[dict]] = {}
    for r in records:
        ref = (r.get("activity_ref") or "").strip()
        if not ref:
            continue
        target = ref if ref in exact else by_core.get(_ref_core(ref))
        if target:
            out.setdefault(target, []).append(r)
    return out
