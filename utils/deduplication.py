"""Teacher name normalisation and duplicate review removal (Spec §4)."""
from __future__ import annotations

import pandas as pd
from utils.helpers import normalize_name, parse_date

# Minimum prefix length to consider two names as the same person.
# "deepak" (6) matches "deepakmunesh" (12); "raj" (3) is too short to match safely.
_MIN_PREFIX = 6


def _same_teacher(a: str, b: str) -> bool:
    """Return True if two normalised names likely refer to the same person.

    Exact match OR one is a prefix of the other (≥ _MIN_PREFIX chars).
    Examples that match: "deepak" / "deepakmunesh", "preethi" / "preethikumar".
    """
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= _MIN_PREFIX and long_.startswith(short)


def _canonical_name_map(norms: list[str]) -> dict[str, str]:
    """Cluster similar names; the longest form in each cluster is canonical."""
    # Sort longest-first so the canonical is always the most complete name
    unique = sorted(set(norms), key=len, reverse=True)
    canon: dict[str, str] = {}
    for norm in unique:
        matched = next((canon[k] for k in canon if _same_teacher(norm, k)), None)
        canon[norm] = matched if matched else norm
    return canon


def deduplicate_reviews(rows: list[dict]) -> list[dict]:
    """
    Apply spec §4 rules:
    1. Normalise teacher names (strip spaces, lowercase).
    2. Cluster names that are prefix-matches of each other (same person).
    3. For the same (canonical_name, activity_ref), keep only the most recent review.
    Returns a cleaned list of rows — still multi-row per lesson, one row per item.
    """
    if not rows:
        return []

    df = pd.DataFrame(rows)

    # Forward-fill lesson-header columns (populated only on first item row)
    header_cols = ["activity_ref", "grade", "chapter", "lesson", "reviewer_name", "reviewer_phone"]
    for col in header_cols:
        if col in df.columns:
            df[col] = df[col].replace("", pd.NA).ffill()

    df["_norm_name"] = df["reviewer_name"].apply(normalize_name)

    # Build canonical name map and apply
    canon_map = _canonical_name_map(df["_norm_name"].fillna("").tolist())
    df["_canon_name"] = df["_norm_name"].map(lambda n: canon_map.get(n, n))

    # Parse review date
    if "review_date" in df.columns:
        df["_parsed_date"] = df["review_date"].apply(parse_date)
    else:
        df["_parsed_date"] = pd.NaT

    review_keys = df[["activity_ref", "_canon_name", "_parsed_date"]].drop_duplicates()

    # Per (activity_ref, canonical teacher), keep only the latest date
    latest = (
        review_keys
        .sort_values("_parsed_date", ascending=False, na_position="last")
        .groupby(["activity_ref", "_canon_name"], as_index=False)
        .first()
    )
    keep_set = set(
        zip(latest["activity_ref"], latest["_canon_name"], latest["_parsed_date"].astype(str))
    )

    mask = df.apply(
        lambda r: (r["activity_ref"], r["_canon_name"], str(r["_parsed_date"])) in keep_set,
        axis=1,
    )
    result = df[mask].drop(columns=["_norm_name", "_canon_name", "_parsed_date"])
    return result.to_dict("records")


def group_by_lesson(rows: list[dict]) -> dict[str, list[dict]]:
    """Group deduplicated rows by activity_ref."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = row.get("activity_ref", "")
        if key:
            grouped.setdefault(key, []).append(row)
    return grouped


def get_unique_teachers(lesson_rows: list[dict]) -> list[str]:
    """Return distinct teacher names for a lesson, merging prefix-match duplicates."""
    seen_norms: list[str] = []
    names: list[str] = []
    for row in lesson_rows:
        norm = normalize_name(row.get("reviewer_name", ""))
        if not norm:
            continue
        if not any(_same_teacher(norm, s) for s in seen_norms):
            seen_norms.append(norm)
            names.append(row.get("reviewer_name", norm))
    return names


# Fields that indicate a reviewer actually submitted feedback (not just a name
# on an error-report row or a blank stub). Used for the "3 reviews" gate.
_FEEDBACK_FIELDS = (
    "understanding", "understanding_details",
    "examples_practice", "examples_practice_details",
    "engagement", "engagement_details",
    "length", "language",
    "practice_quality", "practice_observations",
    "exit_ticket_quality", "exit_ticket_observations",
    "overall_rating", "additional_suggestions",
)


def get_reviewers_with_feedback(lesson_rows: list[dict]) -> list[str]:
    """Distinct reviewers who actually submitted feedback for this lesson.

    A reviewer counts only if at least one of their rows carries a substantive
    feedback field. This prevents error-report rows or blank stubs (which still
    have a reviewer name) from making a lesson look 'complete'.
    """
    norms = [normalize_name(r.get("reviewer_name", "")) for r in lesson_rows]
    canon = _canonical_name_map([n for n in norms if n])

    has_feedback: dict[str, bool] = {}
    display: dict[str, str] = {}
    for row in lesson_rows:
        norm = normalize_name(row.get("reviewer_name", ""))
        if not norm:
            continue
        c = canon.get(norm, norm)
        display.setdefault(c, row.get("reviewer_name", norm))
        substantive = any((row.get(f) or "").strip() for f in _FEEDBACK_FIELDS)
        has_feedback[c] = has_feedback.get(c, False) or substantive

    return [display[c] for c, ok in has_feedback.items() if ok]


def group_errors_by_lesson(errors: list[dict]) -> dict[str, list[dict]]:
    """Group reported errors by activity_ref."""
    grouped: dict[str, list[dict]] = {}
    for e in errors:
        key = e.get("activity_ref", "")
        if key:
            grouped.setdefault(key, []).append(e)
    return grouped
