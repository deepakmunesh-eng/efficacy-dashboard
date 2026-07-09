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

# ── Error signals (trigger the −0.2 penalties) ─────────────────────────────────
# Genuine defects + confusion (per user decision 2026-07-09) — NOT constructive
# suggestions. Reported-error tab entries also trigger the learning penalty.
# NOTE: we deliberately do NOT match bare "error" — teachers suggest adding
# "Find the error" questions, which is a suggestion, not a defect. We match
# "error in" / "an error" / "there is error" instead.
_NEGATIVE_SIGNALS = [
    # incorrect answers / solutions / images
    "incorrect", "inaccurate",
    "wrong answer", "wrong solution", "wrong option", "is wrong", "answer is wrong",
    "error in", "an error", "errors in", "there is error", "has an error",
    "typo", "mistake", "not correct",
    # confusion (user-requested)
    "confusion", "confusing",
    # misleading content / technical bugs
    "misleading", "not working", "doesn't work", "does not work",
    "not popping", "broken",
]

# Classroom coded answers (q1–q5, q7–q9) → 0–5 score. q11 is a 1–5 number.
_CLASSROOM_CODE_SCORES = {
    # q1 — students understood
    "understood_all": 5.0, "needed_support": 3.0,
    # q2 — engagement (learning)
    "highly_engaging": 5.0, "engaging_in_parts": 4.0, "not_engaging": 2.0,
    # q3 — examples / guided practice
    "adequate": 5.0, "more_than_required": 4.0, "less_than_required": 3.0,
    # q4 — language / readability
    "appropriate": 5.0, "text_heavy_some": 3.0, "very_text_heavy": 2.0,
    # q5 — consistent build-up
    "yes_consistently": 5.0, "yes_some_points": 4.0, "limited_no": 3.0,
    # q7 — practice difficulty
    "right_mix": 5.0, "too_easy": 3.0, "too_difficult": 3.0,
    # q8 — practice engagement
    "extremely_engaging": 5.0, "somewhat_engaging": 4.0, "not_engaging_practice": 2.0,
    # q9 — practice variety
    "good_mix": 5.0, "some_variety": 4.0, "very_little_variety": 3.0,
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
