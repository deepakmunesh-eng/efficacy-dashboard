"""Lesson health model — new 4-component spec (Efficacy Review Dashboard, 2026-07-13).

Health of a lesson = weighted blend of FOUR top-level components:

    Teacher Sheet review     40%   (learning items + practice + mini-quiz + overall)
    Class review             30%   (classroom feedback from teachers)
    Exit-ticket data         10%   (student exit-ticket results — a separate source)
    AI review of learning    20%   (AI expert review of the learning items, 1-5)

The weight of any component that has NO data is dropped and the remaining
weights are rescaled to 100%. So, e.g., a lesson with no classroom review, no
exit-ticket data and no AI review yet is scored purely on the teacher sheet.

Errors reported are **NOT** part of health (they are tracked separately).

Health rolls up:  lesson -> chapter -> grade  (simple mean of child scores).
Bands: Good >= 4.0, Average 2.5-3.9, Bad < 2.5 (see scoring.rag_from_score).
"""
from __future__ import annotations

from processing.scoring import rag_from_score

# ── Top-level component weights (must sum to 100) ──────────────────────────────
HEALTH_WEIGHTS = {
    "teacher":   40,
    "classroom": 30,
    "exit_data": 10,
    "ai":        20,
}
HEALTH_LABELS = {
    "teacher":   "Teacher Sheet review",
    "classroom": "Class review",
    "exit_data": "Exit-ticket data",
    "ai":        "AI review",
}

# ── Teacher-sheet internal sub-weights (relative; rescaled over present) ───────
# The teacher sheet (40% of health) is itself a blend of the learning items,
# the practice section, the mini-quiz (exit-ticket) section and the teacher's
# own overall rating. Relative weights preserve the earlier tuning.
TEACHER_SUBWEIGHTS = {
    "learning":  40,
    "practice":  20,
    "mini_quiz":  5,
    "overall":   10,
}


def _blend(components: dict, weights: dict) -> tuple[float, dict, dict]:
    """Weighted mean over components that have data (value > 0), with the used
    weights rescaled to 100%. Returns (score, active_values, effective_pct)."""
    active = {k: round(float(v), 2) for k, v in components.items()
              if v is not None and float(v) > 0}
    if not active:
        return 0.0, {}, {}
    tot_w = sum(weights[k] for k in active) or 1
    eff = {k: round(weights[k] / tot_w * 100) for k in active}
    score = round(sum(active[k] * weights[k] for k in active) / tot_w, 2)
    return score, active, eff


def teacher_sheet_score(learning=None, practice=None, mini_quiz=None,
                        overall=None) -> float:
    """The Teacher Sheet review sub-score (40% component)."""
    score, _, _ = _blend(
        {"learning": learning, "practice": practice,
         "mini_quiz": mini_quiz, "overall": overall},
        TEACHER_SUBWEIGHTS,
    )
    return round(score, 2)


def compute_health(*, teacher=None, classroom=None, exit_data=None,
                   ai=None) -> dict:
    """Compute a lesson's health from the four components (any may be missing)."""
    components = {"teacher": teacher, "classroom": classroom,
                  "exit_data": exit_data, "ai": ai}
    score, active, eff = _blend(components, HEALTH_WEIGHTS)
    if not active:
        return {
            "score": 0.0, "rating": "Pending",
            "components": {}, "weights": {}, "nominal_weights": {},
            "missing": list(components),
        }
    return {
        "score":           round(score, 1),
        "rating":          rag_from_score(round(score, 1)),
        "components":      active,
        "weights":         eff,                       # effective % (rescaled)
        "nominal_weights": {k: HEALTH_WEIGHTS[k] for k in active},
        "missing":         [k for k in components if k not in active],
    }


def rollup(child_scores: list[float]) -> dict:
    """Roll child health scores up to a parent (chapter/grade) — simple mean."""
    vals = [s for s in child_scores if s is not None and float(s) > 0]
    if not vals:
        return {"score": 0.0, "rating": "Pending", "n": 0}
    score = round(sum(vals) / len(vals), 1)
    return {"score": score, "rating": rag_from_score(score), "n": len(vals)}
