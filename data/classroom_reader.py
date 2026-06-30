"""
Pull classroom review submissions directly from the Vercel admin endpoint.
Handles both HTML table responses and JSON API responses automatically.
"""
from __future__ import annotations

import json

import requests
from bs4 import BeautifulSoup

from config.settings import CLASSROOM_ADMIN_URL, CLASSROOM_ADMIN_KEY

CLASSROOM_FIELDS = [
    "teacher_name", "student_name", "class_date", "class_time",
    "grade", "chapter", "lesson", "activity_ref",
    "learning_q1", "learning_q2", "learning_q3", "learning_q4", "learning_q5",
    "learning_notes",
    "practice_q7", "practice_q8", "practice_q9",
    "practice_notes",
    "overall_effectiveness",
    "specific_instances",
    "additional_resources",
]


def _fetch_raw() -> requests.Response:
    """GET the admin page with the auth key."""
    resp = requests.get(
        CLASSROOM_ADMIN_URL,
        params={"key": CLASSROOM_ADMIN_KEY},
        timeout=20,
        headers={"Accept": "application/json, text/html, */*"},
    )
    resp.raise_for_status()
    return resp


def _parse_json(data) -> list[dict]:
    """Handle JSON responses — list of dicts or {data: [...]} wrapper."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "reviews", "submissions", "results", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _parse_html_table(html: str) -> list[dict]:
    """Extract the first <table> from the admin HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    headers = [th.get_text(strip=True).lower().replace(" ", "_")
               for th in table.find_all("th")]
    if not headers:
        # Try first row as header
        first_row = table.find("tr")
        if first_row:
            headers = [td.get_text(strip=True).lower().replace(" ", "_")
                       for td in first_row.find_all(["td", "th"])]

    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not any(cells):
            continue
        record = dict(zip(headers, cells + [""] * max(0, len(headers) - len(cells))))
        rows.append(record)
    return rows


def _normalise_record(raw: dict) -> dict:
    """Map raw field names to our standard CLASSROOM_FIELDS schema."""
    # Build a lowercased lookup for fuzzy matching
    lookup = {k.lower().replace(" ", "_").replace("-", "_"): v for k, v in raw.items()}

    result: dict = {}
    for field in CLASSROOM_FIELDS:
        # Try exact match first, then common aliases
        val = lookup.get(field, "")
        if not val:
            aliases = {
                "activity_ref": ["activityref", "activity_reference", "ref", "lessonref"],
                "teacher_name": ["teacher", "teachername", "reviewer"],
                "student_name": ["student", "studentname"],
                "class_date": ["date", "classdate", "session_date"],
                "overall_effectiveness": ["overall", "effectiveness", "q11", "rating"],
                "specific_instances": ["instances", "moments", "q12"],
                "learning_notes": ["learningnotes", "learning_feedback", "q6"],
                "practice_notes": ["practicenotes", "practice_feedback", "q10"],
            }
            for alias in aliases.get(field, []):
                val = lookup.get(alias, "")
                if val:
                    break
        result[field] = str(val).strip() if val else ""
    return result


def fetch_classroom_reviews() -> list[dict]:
    """
    Fetch all classroom review submissions from the admin endpoint.
    Returns a list of normalised records.
    """
    try:
        resp = _fetch_raw()
    except Exception as exc:
        print(f"[classroom_reader] Could not reach admin URL: {exc}")
        return []

    content_type = resp.headers.get("content-type", "")
    records: list[dict] = []

    if "application/json" in content_type or "json" in content_type:
        try:
            raw_records = _parse_json(resp.json())
        except Exception:
            raw_records = []
    else:
        raw_records = _parse_html_table(resp.text)

    for raw in raw_records:
        normalised = _normalise_record(raw)
        if normalised.get("activity_ref") or normalised.get("lesson"):
            records.append(normalised)

    return records


def group_classroom_by_lesson(records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for r in records:
        key = r.get("activity_ref", "").strip()
        if key:
            grouped.setdefault(key, []).append(r)
    return grouped
