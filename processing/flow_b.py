"""Flow B — Activity Level Feedback (Spec §8). Rule-based, no external API."""
from __future__ import annotations

from config.settings import (
    WEIGHTING_LEARNING, WEIGHTING_PRACTICE,
    WEIGHTING_EXIT_TICKET, WEIGHTING_CLASSROOM,
)
from processing.scoring import (
    score_section_row, score_classroom_record, rag_from_score, safe_float,
)
from utils.helpers import normalize_name


def _compute_weights(has_classroom: bool) -> tuple[float, float, float, float]:
    """Return fractional weights (sum to 1.0), redistributing if no classroom data."""
    if has_classroom:
        total = WEIGHTING_LEARNING + WEIGHTING_PRACTICE + WEIGHTING_EXIT_TICKET + WEIGHTING_CLASSROOM
        return (
            WEIGHTING_LEARNING / total,
            WEIGHTING_PRACTICE / total,
            WEIGHTING_EXIT_TICKET / total,
            WEIGHTING_CLASSROOM / total,
        )
    total = WEIGHTING_LEARNING + WEIGHTING_PRACTICE + WEIGHTING_EXIT_TICKET
    return (
        WEIGHTING_LEARNING / total,
        WEIGHTING_PRACTICE / total,
        WEIGHTING_EXIT_TICKET / total,
        0.0,
    )


_BACKFILL_FIELDS = (
    "overall_rating", "additional_suggestions",
    "practice_quality", "practice_observations",
    "exit_ticket_quality", "exit_ticket_observations",
)


def _section_teacher_rows(lesson_rows: list[dict]) -> list[dict]:
    """One row per unique teacher with section-level fields merged from all their rows.

    In merged-cell Google Sheets exports, overall_rating and suggestions appear on
    the last/summary row, not the first item row. We take a mutable copy of the first
    row and backfill any missing fields from subsequent rows for the same teacher.
    """
    seen: set[str] = set()
    rows: list[dict] = []
    for row in lesson_rows:
        norm = normalize_name(row.get("reviewer_name", ""))
        if norm and norm not in seen:
            seen.add(norm)
            rows.append(dict(row))  # mutable copy
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


def _learning_score_from_flow_a(flow_a_results: list[dict]) -> tuple[float, bool, int, int]:
    """Return (avg_score, majority_bad, rated_count, total_count).

    Only items that are actually rated (Good/Average/Bad — i.e. reviewed by ≥3
    teachers) contribute to the score. `rated_count` vs `total_count` lets the
    caller tell when the section is only partially reviewed (some items Pending),
    so it isn't misleadingly marked Good/Average off a single rated item.
    """
    total = len(flow_a_results)
    rated = [r for r in flow_a_results
             if r.get("rating") in ("Good", "Average", "Bad") and r.get("score")]
    if not rated:
        return 3.0, False, 0, total
    avg = sum(r["score"] for r in rated) / len(rated)
    bad_count = sum(1 for r in rated if r.get("rating") == "Bad")
    majority_bad = bad_count > len(rated) / 2
    return round(avg, 2), majority_bad, len(rated), total


def _build_section_summary(label: str, score: float, teacher_rows: list[dict],
                            obs_field: str, quality_field: str) -> dict:
    rating = rag_from_score(score)
    observations = [r.get(obs_field, "").strip() for r in teacher_rows if r.get(obs_field)]
    quality_vals  = [r.get(quality_field, "").strip() for r in teacher_rows if r.get(quality_field)]
    rationale = f"Average {label} score: {score:.1f}/5 from {len(teacher_rows)} teacher(s)."
    if observations:
        rationale += " Key observations: " + " | ".join(observations[:3])[:300]
    return {"rating": rating, "score": round(score, 2), "rationale": rationale}


def _build_recommendations(section_ratings: dict, flow_a_results: list[dict],
                            majority_bad: bool) -> list[str]:
    recs = []
    for section, label in [("learning","Learning"), ("practice","Practice"),
                            ("exit_ticket","Exit Ticket"), ("classroom_review","Classroom")]:
        rating = section_ratings.get(section, {}).get("rating", "")
        if rating == "Bad":
            recs.append(f"Revise {label} section — scored below threshold.")
        elif rating == "Average":
            recs.append(f"Improve {label} section — meets minimum but has noted gaps.")

    bad_items = [r["item_ref"] for r in flow_a_results if r.get("rating") == "Bad"]
    if bad_items:
        recs.append(f"Priority item revisions needed: {', '.join(bad_items[:5])}")

    div_items = [r["item_ref"] for r in flow_a_results if r.get("divergences")]
    if div_items:
        recs.append(
            f"Review teacher divergences on items: {', '.join(div_items[:5])}. "
            "Consider scheduling a calibration session."
        )

    if not recs:
        recs.append("Lesson is performing well. Consider sharing as a model lesson.")

    return recs[:5]


def run_flow_b(
    activity_ref: str,
    lesson_rows: list[dict],
    flow_a_results: list[dict],
    classroom_records: list[dict],
    learnosity_content: dict,
) -> dict:
    meta = next((r for r in lesson_rows if r.get("activity_ref")), lesson_rows[0] if lesson_rows else {})
    grade, chapter, lesson = meta.get("grade",""), meta.get("chapter",""), meta.get("lesson","")

    teachers = _section_teacher_rows(lesson_rows)
    has_classroom = bool(classroom_records)
    w_l, w_p, w_e, w_c = _compute_weights(has_classroom)

    # ── Section scores ────────────────────────────────────────────────────────
    # Learning: from Flow A
    learning_score, majority_bad, rated_items, total_items_la = _learning_score_from_flow_a(flow_a_results)
    # The learning section is only "complete" when every item has ≥3 reviews.
    # If any item is still Pending, we must not present a confident Good/Average.
    # No learning items → nothing to block on; otherwise require all items rated.
    learning_complete = (total_items_la == 0) or (rated_items == total_items_la)
    learning_pending  = max(total_items_la - rated_items, 0)

    # Practice + Exit Ticket: from section-level teacher rows
    section_scores = [score_section_row(r) for r in teachers]
    avg_practice    = sum(s["practice_score"] for s in section_scores) / max(len(section_scores), 1)
    avg_exit        = sum(s["exit_ticket_score"] for s in section_scores) / max(len(section_scores), 1)
    teacher_ratings = [s["overall_rating"] for s in section_scores]
    valid_ratings   = [x for x in teacher_ratings if x > 0]
    avg_teacher_rating = round(sum(valid_ratings) / len(valid_ratings), 2) if valid_ratings else 0.0

    # Classroom: aggregate all records
    classroom_score = 0.0
    if classroom_records:
        cr_scores = [score_classroom_record(r) for r in classroom_records]
        classroom_score = round(sum(cr_scores) / len(cr_scores), 2)

    # ── Section ratings ───────────────────────────────────────────────────────
    # The learning section is rated as an aggregate of the individual item
    # ratings (each item is rated from whatever teacher reviews it has).
    learning_summary = _build_section_summary(
        "Learning", learning_score, teachers, "understanding_details", "understanding"
    )

    section_ratings: dict = {
        "learning": learning_summary,
        "practice": _build_section_summary(
            "Practice", avg_practice, teachers, "practice_observations", "practice_quality"
        ),
        "exit_ticket": _build_section_summary(
            "Exit Ticket", avg_exit, teachers, "exit_ticket_observations", "exit_ticket_quality"
        ),
        "teacher_overall": {
            "rating": rag_from_score(avg_teacher_rating) if avg_teacher_rating > 0 else "N/A",
            "score": round(avg_teacher_rating, 2),
            "rationale": (
                f"Teachers' self-reported overall rating: {avg_teacher_rating:.1f}/5 "
                f"(average of {len(valid_ratings)} explicit rating(s))."
                if valid_ratings
                else "No explicit overall ratings provided by teachers."
            ),
        },
        "classroom_review": {
            "rating": rag_from_score(classroom_score) if has_classroom else "N/A",
            "score": classroom_score,
            "rationale": (
                f"Aggregated {len(classroom_records)} classroom session(s). "
                f"Average score: {classroom_score:.1f}/5."
                if has_classroom else "No classroom reviews available."
            ),
        },
    }

    # ── Weighted final score ──────────────────────────────────────────────────
    weighted = (
        learning_score * w_l
        + avg_practice  * w_p
        + avg_exit      * w_e
        + (classroom_score * w_c if has_classroom else 0)
    )
    weighted = round(weighted, 2)

    # Teacher's holistic self-rating carries equal weight (50%) to the
    # algorithmic section scores — it is the strongest single signal.
    if avg_teacher_rating > 0:
        weighted = round(weighted * 0.50 + avg_teacher_rating * 0.50, 2)

    # Divergence penalty: when teachers significantly disagree on items,
    # confidence in the lesson quality is reduced.
    items_with_divergence = sum(1 for r in flow_a_results if r.get("divergences"))
    total_items = max(len(flow_a_results), 1)
    divergence_ratio = items_with_divergence / total_items
    has_divergence = items_with_divergence > 0
    div_penalty = 0.0
    if has_divergence:
        div_penalty = round(divergence_ratio * 0.5, 2)
        weighted = max(1.0, round(weighted - div_penalty, 2))

    # ── Flow A constraint: majority bad → cannot be Good ─────────────────────
    override_applied = False
    override_rationale = ""
    final_rating = rag_from_score(weighted)

    if majority_bad and final_rating == "Good":
        final_rating = "Average"
        override_applied = True
        override_rationale = (
            "Majority of learning items rated Bad by Flow A. "
            "Final rating capped at Average per spec constraint."
        )

    # ── Summary text ──────────────────────────────────────────────────────────
    section_labels = {"Good": "strong", "Average": "acceptable", "Bad": "weak"}
    parts = [
        f"Learning {section_labels.get(section_ratings['learning']['rating'],'?')}",
        f"Practice {section_labels.get(section_ratings['practice']['rating'],'?')}",
        f"Exit Ticket {section_labels.get(section_ratings['exit_ticket']['rating'],'?')}",
    ]
    if has_classroom:
        parts.append(f"Classroom {section_labels.get(section_ratings['classroom_review']['rating'],'?')}")
    one_line = f"{final_rating} — " + ", ".join(parts) + "."

    div_note = (
        f" ⚠️ {items_with_divergence}/{total_items} item(s) flagged for teacher divergence"
        f" (−{div_penalty:.2f} penalty)." if has_divergence else ""
    )
    teacher_blend_note = (
        f" Teacher self-rating {avg_teacher_rating:.1f}/5 blended in (50% weight).{div_note}"
        if avg_teacher_rating > 0 else div_note
    )
    final_rationale = (
        f"Weighted score: {weighted:.2f}/5 "
        f"(Learning {learning_score:.1f}×{w_l:.0%}, "
        f"Practice {avg_practice:.1f}×{w_p:.0%}, "
        f"Exit Ticket {avg_exit:.1f}×{w_e:.0%}"
        + (f", Classroom {classroom_score:.1f}×{w_c:.0%}" if has_classroom else "")
        + f").{teacher_blend_note} "
        + ("No classroom reviews — weights redistributed. " if not has_classroom else "")
        + (override_rationale if override_applied else "")
    )

    recommendations = _build_recommendations(section_ratings, flow_a_results, majority_bad)

    return {
        "activity_ref":              activity_ref,
        "grade":                     grade,
        "chapter":                   chapter,
        "lesson":                    lesson,
        "section_ratings":           section_ratings,
        "weighted_score":            weighted,
        "final_rating":              final_rating,
        "override_applied":          override_applied,
        "override_rationale":        override_rationale,
        "final_rationale":           final_rationale,
        "one_line_summary":          one_line,
        "actionable_recommendations": recommendations,
        "teacher_names":             [r.get("reviewer_name","") for r in teachers],
        "teacher_ratings":           teacher_ratings,
        "avg_teacher_rating":        avg_teacher_rating,
        "has_divergence":            has_divergence,
        "divergence_count":          items_with_divergence,
        "learning_complete":         learning_complete,
        "learning_items_rated":      rated_items,
        "learning_items_total":      total_items_la,
        "flow_a_results":            flow_a_results,
        "weights": {
            "learning":     round(w_l * 100),
            "practice":     round(w_p * 100),
            "exit_ticket":  round(w_e * 100),
            "classroom":    round(w_c * 100),
        },
    }
