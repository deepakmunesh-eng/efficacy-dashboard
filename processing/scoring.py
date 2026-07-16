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

# ── Severity-scaled error penalties (per user decision 2026-07-10) ─────────────
# Detected from ANY free-response box (item details, practice/exit observations,
# additional suggestions) AND the Errors Reported tab. Penalty scales with
# severity: SEVERE −1.5, MODERATE −1.0, MINOR −0.5. Take the most severe present.
# NOTE: we deliberately do NOT match bare "error"/"wrong" — teachers suggest
# adding "Find the error" questions (a suggestion) and write "nothing wrong".
_SEVERE_PENALTY   = 1.5
_MODERATE_PENALTY = 1.0
_MINOR_PENALTY    = 0.5
# Back-compat alias (flow_b imports _HARD_PENALTY for a display comparison).
_HARD_PENALTY = _SEVERE_PENALTY

_SEVERE_SIGNALS = [   # genuine content errors
    "incorrect", "inaccurate",
    "wrong answer", "wrong solution", "wrong option", "answer is wrong",
    "error in", "an error", "errors in", "there is error", "has an error",
    "not correct", "typo", "mistake",
]
_MODERATE_SIGNALS = [  # real defects / bugs / mismatches
    "misleading", "not working", "doesn't work", "does not work", "not popping",
    "broken", "inconsistent", "does not match", "doesn't match", "not aligned",
    "not visible", "cut off", "cut-off", "overlap", "overlapping",
]
_MINOR_SIGNALS = [     # confusion / clarity
    "confusion", "confusing", "confuse", "unclear", "not clear",
    "hard to read", "hard to understand", "difficult to read", "difficult to understand",
]


def classify_error(*texts: str) -> tuple[float, str]:
    """(penalty, severity_label) for the most severe signal in the text(s),
    or (0.0, '') if none. Severity: severe −1.5, moderate −1.0, minor −0.5."""
    blob = " ".join((t or "").lower() for t in texts)
    if any(s in blob for s in _SEVERE_SIGNALS):
        return _SEVERE_PENALTY, "severe"
    if any(s in blob for s in _MODERATE_SIGNALS):
        return _MODERATE_PENALTY, "moderate"
    if any(s in blob for s in _MINOR_SIGNALS):
        return _MINOR_PENALTY, "minor"
    return 0.0, ""


def penalty_for(*texts: str, has_reported_error: bool = False) -> float:
    """Severity-scaled penalty for the text(s). A reported error with no matching
    keyword still counts as at least MODERATE (it is a flagged defect)."""
    pen, _ = classify_error(*texts)
    if pen == 0.0 and has_reported_error:
        pen = _MODERATE_PENALTY
    return pen


def has_negative_feedback(*texts: str) -> bool:
    """Backward-compatible boolean: any error signal present."""
    return classify_error(*texts)[0] > 0


# Classroom coded answers (q1–q5, q7–q9) → 1–5 score. q11 is a 1–5 number.
# Values follow the rubric in "classroom ratings.txt" exactly.
_CLASSROOM_CODE_SCORES = {
    # q1 — student understood the learning section
    "understood_all": 5.0, "needed_support": 3.0, "not_understood": 2.0,
    # q2 — how the student experienced the learning section
    "highly_engaging": 5.0, "engaging_in_parts": 3.0, "not_engaging": 2.0,
    # q3 — guided examples & tasks
    "more_than_required": 5.0, "adequate": 4.0, "less_than_required": 3.0,
    # q4 — language / readability
    "appropriate": 5.0, "text_heavy_some": 3.0, "very_text_heavy": 2.0,
    # q5 — discussion opportunities
    "yes_consistently": 5.0, "yes_some_points": 3.0, "limited_no": 2.0,
    # q7 — practice difficulty
    "right_mix": 5.0, "too_easy": 3.0, "too_difficult": 2.0,
    # q8 — practice engagement
    "extremely_engaging": 5.0, "somewhat_engaging": 3.0, "not_engaging_practice": 2.0,
    # q9 — practice variety
    "good_mix": 5.0, "some_variety": 3.0, "very_little_variety": 2.0,
    # "other" / blank → skipped (not scored)
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
    """Aggregate a single classroom review record to a 1–5 score.

    Averages the mapped q1–q5 / q7–q9 coded answers plus the teacher's q11
    overall-effectiveness rating (1–5). Unknown/'other' answers are skipped.
    """
    q_scores = []
    for q in ["learning_q1", "learning_q2", "learning_q3", "learning_q4", "learning_q5",
              "practice_q7", "practice_q8", "practice_q9"]:
        code = (record.get(q, "") or "").strip().lower()
        if code in _CLASSROOM_CODE_SCORES:
            q_scores.append(_CLASSROOM_CODE_SCORES[code])

    q11 = safe_float(record.get("overall_effectiveness"), 0.0)
    if q11:
        q_scores.append(q11)

    return round(sum(q_scores) / len(q_scores), 2) if q_scores else 3.0


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
