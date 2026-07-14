"""Flow B — Lesson-level health (new 4-component spec, 2026-07-13).

Health of a lesson = weighted blend (see processing.health):
    Teacher Sheet review   40%   (learning items + practice + mini-quiz + overall)
    Class review           30%   (classroom feedback)
    Exit-ticket data       10%   (student exit-ticket results — separate source)
    AI review              20%   (AI expert review of learning items, 1-5)
Weights of missing components are dropped and the rest rescaled to 100%.

Section scores (no penalties — errors are tracked separately, not in health):
    Learning     = average of the learning-item ratings (Flow A)
    Practice     = average of the practice option scores across teachers
    Mini-Quiz    = average of the exit-ticket / mini-quiz option scores
    Overall      = average of the teachers' own 1-5 overall rating
    Classroom    = average of the classroom review records
"""
from __future__ import annotations

from processing.scoring import (
    score_section_row, score_classroom_record, rag_from_score,
)
from processing.health import compute_health, teacher_sheet_score
from utils.helpers import normalize_name

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


def _section_dict(score: float, rating: str, rationale: str) -> dict:
    return {"score": round(score, 1), "rating": rating, "rationale": rationale}


def _build_recommendations(section_ratings: dict, flow_a_results: list[dict]) -> list[str]:
    recs = []
    for section, label in [("learning", "Learning"), ("practice", "Practice"),
                            ("exit_ticket", "Mini-Quiz"), ("classroom_review", "Classroom")]:
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
    ai_score: float | None = None,
    exit_data_score: float | None = None,
) -> dict:
    """Compute a lesson's health. `ai_score` (1-5) and `exit_data_score` (1-5)
    can be supplied when available; missing components are rescaled out."""
    error_reports = error_reports or []
    meta = next((r for r in lesson_rows if r.get("activity_ref")),
                lesson_rows[0] if lesson_rows else {})
    grade, chapter, lesson = meta.get("grade", ""), meta.get("chapter", ""), meta.get("lesson", "")

    teachers = _section_teacher_rows(lesson_rows)
    section_scores = [score_section_row(r) for r in teachers]

    # ── Teacher-sheet sections (no penalties) ─────────────────────────────────
    rated = [r["score"] for r in flow_a_results
             if r.get("rating") in ("Good", "Average", "Bad") and r.get("score")]
    learning_score = round(sum(rated) / len(rated), 1) if rated else 0.0
    practice_score = round(_avg([s["practice_score"] for s in section_scores]), 1)
    mini_quiz_score = round(_avg([s["exit_ticket_score"] for s in section_scores]), 1)
    overall_score = round(_avg([s["overall_rating"] for s in section_scores]), 1)

    teacher_score = teacher_sheet_score(
        learning=learning_score or None,
        practice=practice_score or None,
        mini_quiz=mini_quiz_score or None,
        overall=overall_score or None,
    )

    # ── Class review (30%) ────────────────────────────────────────────────────
    has_classroom = bool(classroom_records)
    classroom_score = (
        round(sum(score_classroom_record(r) for r in classroom_records)
              / len(classroom_records), 2)
        if has_classroom else 0.0
    )

    # ── Health (4 components, missing ones rescaled out) ──────────────────────
    health = compute_health(
        teacher=teacher_score or None,
        classroom=classroom_score or None,
        exit_data=exit_data_score,
        ai=ai_score,
    )
    weighted = health["score"]
    final_rating = health["rating"]

    # ── Section ratings for display ────────────────────────────────────────────
    def _sec(label, score):
        if not score:
            return _section_dict(0.0, "N/A", f"No {label.lower()} feedback provided.")
        r = rag_from_score(score)
        return _section_dict(
            score, r,
            f"{r} — average {label} score {score:.1f}/5 from {len(teachers)} teacher(s). "
            "Bands: Good ≥4.0, Average 2.5–3.9, Bad <2.5.",
        )

    section_ratings = {
        "learning":    _sec("Learning", learning_score),
        "practice":    _sec("Practice", practice_score),
        "exit_ticket": _sec("Mini-Quiz", mini_quiz_score),
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

    # ── Rationale (shows the component maths) ─────────────────────────────────
    from processing.health import HEALTH_LABELS
    parts = [f"{HEALTH_LABELS[k]} {health['components'][k]:.1f}×{health['weights'][k]}%"
             for k in health["components"]]
    missing_labels = [HEALTH_LABELS[k] for k in health["missing"]]
    final_rationale = (
        f"Health {weighted:.1f}/5 = " + " + ".join(parts) + ". "
        + (f"Not yet available (weight redistributed): {', '.join(missing_labels)}. "
           if missing_labels else "")
        + "Bands: Good ≥4.0, Average 2.5–3.9, Bad <2.5."
    )

    section_labels = {"Good": "strong", "Average": "acceptable", "Bad": "weak", "N/A": "n/a"}
    one_line = (
        f"{final_rating} — Learning {section_labels.get(section_ratings['learning']['rating'],'?')}, "
        f"Practice {section_labels.get(section_ratings['practice']['rating'],'?')}, "
        f"Mini-Quiz {section_labels.get(section_ratings['exit_ticket']['rating'],'?')}."
    )

    return {
        "activity_ref":              activity_ref,
        "grade":                     grade,
        "chapter":                   chapter,
        "lesson":                    lesson,
        "section_ratings":           section_ratings,
        # Teacher-sheet component + its parts
        "teacher_score":             teacher_score,
        "teacher_parts":             {
            "learning": learning_score, "practice": practice_score,
            "mini_quiz": mini_quiz_score, "overall": overall_score,
        },
        # Health (4-component) — the headline
        "health":                    health,
        "weighted_score":            weighted,
        "final_rating":              final_rating,
        "final_rationale":           final_rationale,
        "one_line_summary":          one_line,
        "actionable_recommendations": _build_recommendations(section_ratings, flow_a_results),
        "teacher_names":             [r.get("reviewer_name", "") for r in teachers],
        "teacher_ratings":           [s["overall_rating"] for s in section_scores],
        "avg_teacher_rating":        overall_score,
        "has_divergence":            any(r.get("divergences") for r in flow_a_results),
        "divergence_count":          sum(1 for r in flow_a_results if r.get("divergences")),
        "flow_a_results":            flow_a_results,
    }
