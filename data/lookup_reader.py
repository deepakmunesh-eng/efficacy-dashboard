"""
Fetch grade / chapter / lesson metadata from the curriculum tracking sheet.
Used to backfill rows from old feedback tabs that lack those columns.

Sheet: https://docs.google.com/spreadsheets/d/1zAjDQhJ4dUNWBaNYGtivLFak5BKfUFQb2dB8MHjouT4
Tabs used:
  "Reviewed"       — header on row 1, columns: Grade | Chapter Name | Lesson Name | Activity Reference ID
  "Yet to Review"  — header on row 0, same columns
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import requests

from config.settings import LESSON_LOOKUP_XLSX_URL


def _parse_reviewed(xl: pd.ExcelFile) -> pd.DataFrame:
    df = xl.parse("Reviewed", header=1, dtype=str)
    df = df.rename(columns={
        "Grade":                "grade",
        "Chapter Name":         "chapter",
        "Lesson Name":          "lesson",
        "Activity Reference ID":"activity_ref",
    })
    return df[["grade", "chapter", "lesson", "activity_ref"]].dropna(subset=["activity_ref"])


def _parse_yet_to_review(xl: pd.ExcelFile) -> pd.DataFrame:
    df = xl.parse("Yet to Review", header=0, dtype=str)
    df = df.rename(columns={
        "Grade":                "grade",
        "Chapter Name":         "chapter",
        "Lesson Name":          "lesson",
        "Activity Reference ID":"activity_ref",
    })
    return df[["grade", "chapter", "lesson", "activity_ref"]].dropna(subset=["activity_ref"])


def fetch_lesson_lookup() -> dict[str, dict]:
    """
    Returns a dict keyed by activity_ref → {grade, chapter, lesson}.
    "Reviewed" tab takes precedence over "Yet to Review" for the same ref.
    """
    resp = requests.get(LESSON_LOOKUP_XLSX_URL, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    xl = pd.ExcelFile(BytesIO(resp.content), engine="openpyxl")

    frames = []
    for parser in [_parse_yet_to_review, _parse_reviewed]:  # Reviewed last → wins on dedup
        try:
            frames.append(parser(xl))
        except Exception as exc:
            print(f"[lookup_reader] skipped a tab: {exc}")

    if not frames:
        return {}

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["activity_ref"].str.strip() != ""]
    # Keep last occurrence per ref (Reviewed tab wins because it's appended last)
    combined = combined.drop_duplicates(subset=["activity_ref"], keep="last")

    lookup: dict[str, dict] = {}
    for _, row in combined.iterrows():
        ref = str(row["activity_ref"]).strip()
        lookup[ref] = {
            "grade":   str(row.get("grade", "") or "").strip(),
            "chapter": str(row.get("chapter", "") or "").strip(),
            "lesson":  str(row.get("lesson", "") or "").strip(),
        }
    return lookup
