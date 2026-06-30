"""
Read ALL tabs from the Lesson Review Google Sheet via direct HTTP download.
No API key or service account required — sheet must be shared as
"Anyone with the link can view".

Column mapping is done by header name (case-insensitive) so different tab
layouts (old Feedbacks vs new Feedbacks 15th June onwards) are handled correctly.
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import requests

from config.settings import LESSON_REVIEW_XLSX_URL

# Canonical header text (lowercase, stripped) → internal field name.
# Handles both old tab format (no Review Date/Chapter/Lesson) and
# the new format introduced from 15th June.
_HEADER_MAP: dict[str, str] = {
    "review date":                    "review_date",
    "activity reference":             "activity_ref",
    "grade":                          "grade",
    "grade of the chapter":           "grade",
    "chapter":                        "chapter",
    "lesson":                         "lesson",
    "reviewer name":                  "reviewer_name",
    "reviewer phone":                 "reviewer_phone",
    "item reference":                 "item_ref",
    # Understanding
    "by the end of this learning item, most students will:": "understanding",
    "understanding (details)":        "understanding_details",
    # Examples & Practice
    "does the learning item have enough examples and guided practice to reinforce the learning?": "examples_practice",
    "examples & practice (details)":  "examples_practice_details",
    # Engagement
    "how engaging/fun is this item?": "engagement",
    "engagement (details)":           "engagement_details",
    # Length / Language
    "the learning item is:":          "length",
    "the language used in this learning item:": "language",
    # Practice
    "the questions in the practice section are:": "practice_quality",
    "practice section: (details)":    "practice_observations",   # old format
    "practice section key observations": "practice_observations", # new format
    # Exit ticket (new format only)
    "the questions in the exit ticket section are:": "exit_ticket_quality",
    "exit ticket key observations":   "exit_ticket_observations",
    # Summary
    "overall rating":                 "overall_rating",
    "additional suggestions":         "additional_suggestions",
}

_ALL_FIELDS = list(dict.fromkeys(_HEADER_MAP.values()))  # ordered, unique


def _download_workbook() -> BytesIO:
    resp = requests.get(LESSON_REVIEW_XLSX_URL, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return BytesIO(resp.content)


def _parse_sheet(df: pd.DataFrame) -> list[dict]:
    """Map columns by header name → field. Unknown headers are ignored."""
    col_to_field: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in _HEADER_MAP:
            col_to_field[col] = _HEADER_MAP[key]

    rows = []
    for _, raw in df.iterrows():
        record: dict = {f: "" for f in _ALL_FIELDS}
        for col, field in col_to_field.items():
            val = raw[col]
            record[field] = "" if pd.isna(val) else str(val).strip()
        rows.append(record)
    return rows


def fetch_all_lesson_reviews() -> list[dict]:
    """
    Download the workbook, read every tab, return a flat list of row dicts.
    Completely empty rows are dropped.
    """
    buf = _download_workbook()
    xl = pd.ExcelFile(buf, engine="openpyxl")

    all_rows: list[dict] = []
    for sheet_name in xl.sheet_names:
        try:
            df = xl.parse(sheet_name, header=0, dtype=str)
            rows = _parse_sheet(df)
            for r in rows:
                r["_source_tab"] = sheet_name
            all_rows.extend(rows)
        except Exception as exc:
            print(f"[sheets_reader] Skipping tab '{sheet_name}': {exc}")

    # Keep any row that has at least one meaningful content field.
    # Sub-item rows in merged-cell Excel exports have blank activity_ref and overall_rating
    # but contain item-level data (understanding, engagement, item_ref, etc.).
    # They are forward-filled in deduplicate_reviews(), so we must not drop them here.
    _KEEP_FIELDS = {
        "activity_ref", "item_ref", "reviewer_name",
        "understanding", "engagement", "examples_practice",
        "overall_rating",
    }
    return [
        r for r in all_rows
        if any(r.get(f, "").strip() for f in _KEEP_FIELDS)
    ]
