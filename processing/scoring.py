"""
Rule-based scoring engine (rating logic per ratings.txt, 2026-07-09).

Every learning-item dimension is a direct 0–5 score (Length is now a score, not
a multiplier). Practice/Exit are the average of the selected option scores.
Penalties are targeted −0.2 for reported errors / negative feedback, applied per
section (no divergence penalty). See _build in flow_b for how they combine.
"""
from __future__ import annotations

import re

from utils.helpers import safe_float

# ── Learning-item dimension scores (exact answer text → score) ─────────────────
# Ordered lists: the first matching substring wins (put negatives first so
# "Not understand…" is matched before "…understand the concepts clearly").
_UNDERSTANDING = [
    ("not understand",           2.0),
    ("need significant support", 3.0),
    ("understand the concepts",  5.0),
]
_EXAMPLES = [
    ("more examples",    3.0),   # "No, more examples or guided questions are needed."
    ("adequate examples", 5.0),
]
_ENGAGEMENT = [
    ("needs more",      3.0),    # "Needs more fun/engagement."
    ("quite engaging",  5.0),
]
_LENGTH = [
    ("just the right length", 5.0),
    ("too short",             3.0),
    ("too long",              3.0),
]
_LANGUAGE = [
    ("text heavy",               3.0),
    ("difficult words",          3.0),
    ("clear and age-appropriate", 5.0),
]

# ── Practice / Exit-ticket option scores (multi-select, pipe-separated) ────────
_PRACTICE_OPTIONS = [
    ("just the right mix", 5.0),
    ("fun and engaging",   5.0),
    ("too easy",           3.0),
    ("too difficult",      3.0),
    ("not engaging",       3.0),
]

# ── Negative-feedback / error signals (trigger the −0.2 penalties) ─────────────
_NEGATIVE_SIGNALS = [
    "incorrect", "error", "wrong", "mistake", "typo", "confus", "unclear",
    "not clear", "misleading", "broken", "cut off", "cut-off", "overlap",
    "does not", "doesn't", "not correct", "inconsistent", "missing",
]

# Classroom Q1-Q5, Q7-Q9 4-option dropdowns → 1–4 scale
_CLASSROOM_OPTION_SCORES = {
    "strongly agree":    4, "agree":          3, "disagree":      2, "strongly disagree": 1,
    "excellent":         4, "good":           3, "average":       2, "poor":              1,
    "always":            4, "usually":        3, "sometimes":     2, "rarely":            1,
    "very engaging":     4, "engaging":       3, "somewhat":      2, "not engaging":      1,
    "well":              4, "mostly":         3, "partially":     2, "not well":          1,
    "very appropriate":  4, "appropriate":    3, "not appropriate":   1,
    "too challenging":   2, "just right":     4, "too easy":      2, "very easy":         1,
}


def _match_score(text: str, table: list) -> float | None:
    """First matching substring's score, or None when the field is blank."""
    t = (text or "").lower().strip()
    if not t:
        return None
    for needle, score in table:
        if needle in t:
            return score
    return 3.0  # non-blank but unrecognised → neutral


def has_negative_feedback(*texts: str) -> bool:
    """True if any error / negative-feedback signal appears in the given text(s)."""
    blob = " ".join((t or "").lower() for t in texts)
    return any(sig in blob for sig in _NEGATIVE_SIGNALS)


def _multi_select_score(text: str) -> float | None:
    """Average of the selected practice/exit options (pipe-separated)."""
    t = (text or "").strip()
    if not t:
        return None
    scores = []
    for part in t.split("|"):
        s = _match_score(part, _PRACTICE_OPTIONS)
        if s is not None:
            scores.append(s)
    return round(sum(scores) / len(scores), 2) if scores else None


def overall_rating_score(text: str) -> float:
    """Parse the teacher's 1–5 overall rating (e.g. '4 - Very Good: …' → 4.0)."""
    m = re.match(r"\s*([1-5])", (text or "").strip())
    return float(m.group(1)) if m else 0.0


# ── Public scoring functions ───────────────────────────────────────────────────

def score_item_row(row: dict) -> dict[str, float]:
    """Score one teacher's learning-item row. item_score = mean of the 5
    dimensions (Length is now a direct dimension, not a multiplier)."""
    dims = {
        "understanding": _match_score(row.get("understanding", ""),      _UNDERSTANDING),
        "examples":      _match_score(row.get("examples_practice", ""),  _EXAMPLES),
        "engagement":    _match_score(row.get("engagement", ""),         _ENGAGEMENT),
        "length":        _match_score(row.get("length", ""),             _LENGTH),
        "language":      _match_score(row.get("language", ""),           _LANGUAGE),
    }
    present = [v for v in dims.values() if v is not None]
    item_score = round(sum(present) / len(present), 2) if present else 3.0
    # Keep neutral 3.0 for any blank dim in the returned per-dimension view.
    out = {k: (v if v is not None else 3.0) for k, v in dims.items()}
    out["item_score"] = item_score
    return out


def score_section_row(row: dict) -> dict[str, float]:
    """Practice + exit-ticket option scores and the teacher's overall rating."""
    practice    = _multi_select_score(row.get("practice_quality", ""))
    exit_ticket = _multi_select_score(row.get("exit_ticket_quality", ""))
    return {
        "practice_score":    practice if practice is not None else 0.0,
        "exit_ticket_score": exit_ticket if exit_ticket is not None else 0.0,
        "overall_rating":    overall_rating_score(row.get("overall_rating", "")),
    }


def score_classroom_record(record: dict) -> float:
    """Aggregate a single classroom review record to a 1–5 score."""
    q_scores = []
    for q in ["learning_q1", "learning_q2", "learning_q3", "learning_q4", "learning_q5",
              "practice_q7", "practice_q8", "practice_q9"]:
        val = record.get(q, "")
        if val:
            s = _classroom_option_score(val)
            if s:
                q_scores.append(s / 4.0 * 5.0)  # rescale 1–4 → 1.25–5.0

    q11 = safe_float(record.get("overall_effectiveness"), 0.0)
    if q11:
        q_scores.append(q11)

    return round(sum(q_scores) / len(q_scores), 2) if q_scores else 3.0


def _classroom_option_score(text: str) -> float:
    t = (text or "").lower().strip()
    for key, val in _CLASSROOM_OPTION_SCORES.items():
        if key in t:
            return float(val)
    return 2.5  # neutral


def detect_divergences(teacher_scores: list[dict[str, float]]) -> list[dict]:
    """Flag dimensions where teachers differ by > 1.5 points (shown as info only —
    no scoring penalty in the current logic)."""
    if len(teacher_scores) < 2:
        return []
    dimensions = ["understanding", "examples", "engagement", "length", "language"]
    divergences = []
    for dim in dimensions:
        vals = [t.get(dim, 3.0) for t in teacher_scores]
        spread = max(vals) - min(vals)
        if spread > 1.5:
            divergences.append({
                "dimension": dim.title(),
                "spread": round(spread, 1),
                "description": (
                    f"Teachers differ by {spread:.1f} points on {dim}. "
                    f"Scores: {', '.join(str(v) for v in vals)}"
                ),
                "teacher_positions": " | ".join(
                    f"T{i+1}: {v}" for i, v in enumerate(vals)
                ),
            })
    return divergences


def rag_from_score(score: float) -> str:
    if score >= 4.0:
        return "Good"
    if score >= 2.5:
        return "Average"
    return "Bad"
