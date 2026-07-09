"""Flow B — Activity/lesson-level rating (rating logic per ratings.txt, 2026-07-09).

Section ratings:
  Learning     = average of the item ratings (Flow A), −0.2 if any reported error
                 or negative learning feedback.
  Practice     = average of the practice option scores across teachers, −0.2 if
                 any negative key observation.
  Exit Ticket  = average of the exit option scores across teachers, −0.2 if any
                 negative key observation.
  Overall      = average of the teachers' 1–5 overall lesson rating.

Lesson rating = weighted blend of the sections that have data:
  Learning 40 · Practice 20 · Exit 5 · Overall 10 · Classroom 25
  (weights of missing sections — e.g. no classroom — are dropped and the rest
  are rescaled). Then −0.2 if the "additional suggestions" flag an error.
No divergence penalty (divergence is shown as info only).
"""
from __future__ import annotations

from processing.scoring import (
    score_section_row, score_classroom_record, rag_from_score, penalty_for,
    _HARD_PENALTY as _HARD_PENALTY_REF,
)
from utils.helpers import normalize_name

# Lesson-level weights (percentages) — see ratings.txt.
_WEIGHTS = {
    "learning":  40,
    "practice":  20,
    "exit":       5,
    "overall":   10,
    "classroom": 25,
}
# Penalties are severity-scaled in scoring.penalty_for: −1.5 for a genuine
# reported error, −0.75 for confusion/clarity/bug wording, else 0.


_BACKFILL_FIELDS = (
    "overall_rating", "additional_suggestions",
    "practice_quality", "practice_observations",
    "exit_ticket_quality", "exit_ticket_observations",
)


def _section_teacher_rows(lesson_rows: list[dict]) -> list[dict]:
    """One row per unique teacher with section-level fields merged from all their
    rows (section fields live on the block's first/summary row)."""
    seen: set[str] = set()
    rows: list[dict] = []
    for row in lesson_rows:
        norm = normalize_name(row.get("reviewer_name", ""))
        if norm and norm not in seen:
            seen.add(norm)
            rows.append(dict(row))
    for teacher_row in rows:
        norm = normalize_name(teacher_row.get("reviewer_name", ""))
        for field in _BACKFILL_FIELDS:
            if not (teacher_row.get(field) or "").strip():
                for row in lesson_rows:
                    if (normalize_name(row.get("reviewer_name", "")) == norm
                            and (row.get(field) or "").strip()):
                        teacher_row[field] = row[field]
                        break
    return rows[:3]


def _avg(vals: list[float], default: float = 0.0) -> float:
    vals = [v for v in vals if v]
    return round(sum(vals) / len(vals), 2) if vals else default


def _section_dict(score: float, rating: str, rationale: str,
                  penalty: bool = False) -> dict:
    return {"score": round(score, 1), "rating": rating,
            "rationale": rationale, "penalty_applied": penalty}


def _build_recommendations(section_ratings: dict, flow_a_results: list[dict]) -> list[str]:
    recs = []
    for section, label in [("learning", "Learning"), ("practice", "Practice"),
                            ("exit_ticket", "Exit Ticket"), ("classroom_review", "Classroom")]:
        rating = section_ratings.get(section, {}).get("rating", "")
        if rating == "Bad":
            recs.append(f"Revise {label} section — scored below threshold.")
        elif rating == "Average":
            recs.append(f"Improve {label} section — meets minimum but has noted gaps.")

    bad_items = [r["item_ref"] for r in flow_a_results if r.get("rating") == "Bad"]
    if bad_items:
        recs.append(f"Priority item revisions needed: {', '.join(bad_items[:5])}")
    if not recs:
        recs.append("Lesson is performing well. Consider sharing as a model lesson.")
    return recs[:5]


def run_flow_b(
    activity_ref: str,
    lesson_rows: list[dict],
    flow_a_results: list[dict],
    classroom_records: list[dict],
    learnosity_content: dict,
    error_reports: list[dict] | None = None,
) -> dict:
    error_reports = error_reports or []
    meta = next((r for r in lesson_rows if r.get("activity_ref")), lesson_rows[0] if lesson_rows else {})
    grade, chapter, lesson = meta.get("grade", ""), meta.get("chapter", ""), meta.get("lesson", "")

    teachers = _section_teacher_rows(lesson_rows)
    section_scores = [score_section_row(r) for r in teachers]

    # ── Learning: average of item ratings, severity-scaled penalty
    rated = [r["score"] for r in flow_a_results
             if r.get("rating") in ("Good", "Average", "Bad") and r.get("score")]
    learning_base = round(sum(rated) / len(rated), 2) if rated else 0.0
    learning_pen = penalty_for(
        *[t for r in lesson_rows for t in (r.get("understanding_details", ""),
                                           r.get("examples_practice_details", ""),
                                           r.get("engagement_details", ""))],
        has_reported_error=bool(error_reports),
    ) if learning_base else 0.0
    learning_score = round(max(1.0, learning_base - learning_pen), 1) if learning_base else 0.0

    # ── Practice: average of option scores, severity-scaled penalty
    practice_base = _avg([s["practice_score"] for s in section_scores])
    practice_pen = penalty_for(*[r.get("practice_observations", "") for r in teachers]) if practice_base else 0.0
    practice_score = round(max(1.0, practice_base - practice_pen), 1) if practice_base else 0.0

    # ── Exit ticket: same shape as practice
    exit_base = _avg([s["exit_ticket_score"] for s in section_scores])
    exit_pen = penalty_for(*[r.get("exit_ticket_observations", "") for r in teachers]) if exit_base else 0.0
    exit_score = round(max(1.0, exit_base - exit_pen), 1) if exit_base else 0.0

    # ── Overall (teachers' own 1–5 rating) and Classroom
    overall_score = _avg([s["overall_rating"] for s in section_scores])
    has_classroom = bool(classroom_records)
    classroom_score = round(sum(score_classroom_record(r) for r in classroom_records) / len(classroom_records), 2) if has_classroom else 0.0

    # ── Weighted lesson score over the sections that actually have data ─────────
    components = {
        "learning":  learning_score,
        "practice":  practice_score,
        "exit":      exit_score,
        "overall":   overall_score,
        "classroom": classroom_score,
    }
    active = {k: v for k, v in components.items() if v > 0}
    tot_w = sum(_WEIGHTS[k] for k in active) or 1
    eff_weights = {k: round(_WEIGHTS[k] / tot_w * 100) for k in active}
    weighted = sum(components[k] * _WEIGHTS[k] for k in active) / tot_w

    # Lesson-wide penalty: errors / negative feedback in additional suggestions.
    lesson_pen = penalty_for(*[r.get("additional_suggestions", "") for r in teachers])
    weighted -= lesson_pen
    weighted = round(max(1.0, weighted), 1)
    final_rating = rag_from_score(weighted)

    # ── Section ratings for display ────────────────────────────────────────────
    def _sec(label, base, score, pen):
        if not base:
            return _section_dict(0.0, "N/A", f"No {label.lower()} feedback provided.")
        r = rag_from_score(score)
        txt = f"{r} — average {label} score {score:.1f}/5 from {len(teachers)} teacher(s)."
        if pen:
            kind = "genuine error" if pen >= _HARD_PENALTY_REF else "confusion / clarity issue"
            txt += f" (−{pen:g} penalty for {kind}.)"
        txt += " Bands: Good ≥4.0, Average 2.5–3.9, Bad <2.5."
        return _section_dict(score, r, txt, bool(pen))

    section_ratings = {
        "learning":    _sec("Learning", learning_base, learning_score, learning_pen),
        "practice":    _sec("Practice", practice_base, practice_score, practice_pen),
        "exit_ticket": _sec("Exit Ticket", exit_base, exit_score, exit_pen),
        "teacher_overall": _section_dict(
            overall_score, rag_from_score(overall_score) if overall_score else "N/A",
            (f"Teachers' overall rating: {overall_score:.1f}/5." if overall_score
             else "No overall rating provided by teachers."),
        ),
        "classroom_review": _section_dict(
            classroom_score, rag_from_score(classroom_score) if has_classroom else "N/A",
            (f"Aggregated {len(classroom_records)} classroom session(s): {classroom_score:.1f}/5."
             if has_classroom else "No classroom reviews available."),
        ),
    }

    # ── Final rationale (clear, shows the weighted maths) ──────────────────────
    parts = [f"{k.title()} {components[k]:.1f}×{eff_weights[k]}%" for k in active]
    final_rationale = (
        f"Weighted lesson score {weighted:.1f}/5 = " + " + ".join(parts) + ". "
        + ("No classroom review — its weight was redistributed. " if not has_classroom else "")
        + (f"−{lesson_pen:g} penalty (errors/negative feedback in suggestions). " if lesson_pen else "")
        + "Bands: Good ≥4.0, Average 2.5–3.9, Bad <2.5."
    )

    section_labels = {"Good": "strong", "Average": "acceptable", "Bad": "weak", "N/A": "n/a"}
    one_line = (
        f"{final_rating} — Learning {section_labels.get(section_ratings['learning']['rating'],'?')}, "
        f"Practice {section_labels.get(section_ratings['practice']['rating'],'?')}, "
        f"Exit Ticket {section_labels.get(section_ratings['exit_ticket']['rating'],'?')}."
    )

    # Score breakdown for the lesson-level "how it's calculated" panel.
    score_breakdown = {
        "components":    {k: components[k] for k in active},
        "weights":       eff_weights,
        "weighted":      weighted,
        "rating":        final_rating,
        "lesson_penalty": lesson_pen,
        "has_classroom": has_classroom,
    }

    return {
        "activity_ref":              activity_ref,
        "grade":                     grade,
        "chapter":                   chapter,
        "lesson":                    lesson,
        "section_ratings":           section_ratings,
        "weighted_score":            weighted,
        "final_rating":              final_rating,
        "override_applied":          False,
        "override_rationale":        "",
        "final_rationale":           final_rationale,
        "lesson_score_breakdown":    score_breakdown,
        "one_line_summary":          one_line,
        "actionable_recommendations": _build_recommendations(section_ratings, flow_a_results),
        "teacher_names":             [r.get("reviewer_name", "") for r in teachers],
        "teacher_ratings":           [s["overall_rating"] for s in section_scores],
        "avg_teacher_rating":        overall_score,
        "has_divergence":            any(r.get("divergences") for r in flow_a_results),
        "divergence_count":          sum(1 for r in flow_a_results if r.get("divergences")),
        "flow_a_results":            flow_a_results,
        "weights": {
            "learning":    eff_weights.get("learning", 0),
            "practice":    eff_weights.get("practice", 0),
            "exit_ticket": eff_weights.get("exit", 0),
            "overall":     eff_weights.get("overall", 0),
            "classroom":   eff_weights.get("classroom", 0),
        },
    }
