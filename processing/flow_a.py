"""Flow A — Learning Item Feedback (Spec §7). Rule-based, no external API."""
from __future__ import annotations

from utils.helpers import normalize_name
from processing.scoring import (
    score_item_row, detect_divergences, rag_from_score,
)


def _extract_teacher_rows(lesson_rows: list[dict], item_ref: str) -> list[dict]:
    """One row per unique teacher for this item_ref."""
    seen: set[str] = set()
    rows: list[dict] = []
    for row in lesson_rows:
        if row.get("item_ref", "").strip() == item_ref.strip():
            norm = normalize_name(row.get("reviewer_name", ""))
            if norm and norm not in seen:
                seen.add(norm)
                rows.append(row)
    return rows


def _teacher_summary(row: dict, scores: dict) -> dict:
    parts = []
    if row.get("understanding"):
        parts.append(f"Understanding: {row['understanding']}")
    if row.get("understanding_details"):
        parts.append(row["understanding_details"].strip()[:150])
    if row.get("engagement"):
        parts.append(f"Engagement: {row['engagement']}")
    if row.get("engagement_details"):
        parts.append(row["engagement_details"].strip()[:100])
    if row.get("examples_practice"):
        parts.append(f"Examples: {row['examples_practice']}")
    if row.get("length"):
        parts.append(f"Length: {row['length']}")

    concerns = []
    if scores.get("understanding", 5) < 3:
        concerns.append("understanding gaps")
    if scores.get("engagement", 5) < 3:
        concerns.append("low engagement")
    if scores.get("examples", 5) < 3:
        concerns.append("insufficient examples")
    if scores.get("length_mod", 1) < 0.8:
        concerns.append(f"length issue ({row.get('length','')})")

    return {
        "name": row.get("reviewer_name", ""),
        "summary": " | ".join(parts) if parts else "No detailed feedback provided.",
        "key_concerns": ", ".join(concerns) if concerns else "",
    }


def process_learning_item(
    activity_ref: str,
    grade: str,
    chapter: str,
    lesson: str,
    item_ref: str,
    lesson_rows: list[dict],
    learnosity_content: dict,
) -> dict:
    teacher_rows = _extract_teacher_rows(lesson_rows, item_ref)

    # Each item is rated from whatever teacher reviews it has (1, 2, or 3+).
    # We do NOT hold an item as "Pending" just because fewer than 3 teachers
    # happened to review that specific item — the item gets its own rating and
    # the teacher count is shown for transparency.
    if not teacher_rows:
        return {
            "item_ref": item_ref,
            "section": "Learning",
            "rating": "Pending",
            "rationale": "No teacher reviews for this item yet.",
            "teacher_summaries": {},
            "divergences": [],
            "ai_expert_review": {},
            "score": 0.0,
            "teacher_count": 0,
        }

    # Score each teacher's row
    all_scores = [score_item_row(row) for row in teacher_rows]
    n_teachers = len(teacher_rows)

    # Per-dimension AVERAGES across teachers (not just the first teacher).
    _dims = ["understanding", "engagement", "examples", "language"]
    dim_avgs = {d: round(sum(s[d] for s in all_scores) / n_teachers, 1) for d in _dims}
    length_factor = round(sum(s["length_mod"] for s in all_scores) / n_teachers, 2)

    # Base score = mean of each teacher's item score (dimension avg × length factor).
    base_score = round(sum(s["item_score"] for s in all_scores) / n_teachers, 2)

    # Detect divergences and apply a small penalty per diverging dimension.
    divergences = detect_divergences(all_scores)
    penalty = round(len(divergences) * 0.2, 2)

    # Round to 1 decimal FIRST, then rate — so the number shown and the rating
    # always agree (previously 3.97 displayed as "4.0" but rated Average).
    final_score = round(max(1.0, base_score - penalty), 1)
    rating = rag_from_score(final_score)

    # Build per-teacher summaries
    teacher_summaries = {}
    for i, (row, scores) in enumerate(zip(teacher_rows, all_scores)):
        key = f"teacher{i+1}"
        teacher_summaries[key] = _teacher_summary(row, scores)

    # Structured breakdown for the UI "how this is calculated" panel.
    score_breakdown = {
        "teacher_count":       n_teachers,
        "dimension_averages":  dim_avgs,
        "length_factor":       length_factor,
        "base_score":          base_score,
        "divergence_penalty":  penalty,
        "diverging_dimensions": [d["dimension"] for d in divergences],
        "final_score":         final_score,
        "rating":              rating,
    }

    # Concise, accurate rationale (uses averages, matches the shown score/rating).
    div_dims = ", ".join(d["dimension"] for d in divergences)
    rationale = (
        f"{rating} — final score {final_score:.1f}/5, from {n_teachers} teacher review(s). "
        f"Dimension averages: understanding {dim_avgs['understanding']:.1f}, "
        f"engagement {dim_avgs['engagement']:.1f}, examples {dim_avgs['examples']:.1f}, "
        f"language {dim_avgs['language']:.1f}"
        + (f"; length factor ×{length_factor:.2f}" if length_factor < 1.0 else "")
        + f" → base {base_score:.1f}/5."
    )
    if penalty:
        rationale += f" Divergence penalty −{penalty:.1f} (teachers disagreed on {div_dims})."
    rationale += " Bands: Good ≥4.0, Average 2.5–3.9, Bad <2.5."

    # AI expert review placeholder — populated when Learnosity content becomes available
    learnosity_note = learnosity_content.get("note", "")
    content_items = learnosity_content.get("items", [])
    ai_review: dict = {}
    if content_items:
        ai_review = {
            "content_available": True,
            "item_count": len(content_items),
            "overall_assessment": (
                f"{len(content_items)} content item(s) retrieved from Learnosity. "
                "Full AI review will be enabled once AI integration is configured."
            ),
        }
    else:
        ai_review = {
            "content_available": False,
            "overall_assessment": learnosity_note or "Content not yet available.",
        }

    return {
        "item_ref": item_ref,
        "section": "Learning",
        "score": final_score,
        "rating": rating,
        "teacher_count": n_teachers,
        "score_breakdown": score_breakdown,
        "rationale": rationale,
        "teacher_summaries": teacher_summaries,
        "divergences": divergences,
        "ai_expert_review": ai_review,
    }


def run_flow_a(
    activity_ref: str,
    lesson_rows: list[dict],
    learnosity_content: dict,
) -> list[dict]:
    """Run Flow A for all learning items in a lesson."""
    meta = next((r for r in lesson_rows if r.get("activity_ref")), lesson_rows[0] if lesson_rows else {})
    grade, chapter, lesson = meta.get("grade",""), meta.get("chapter",""), meta.get("lesson","")

    seen: set[str] = set()
    item_refs: list[str] = []
    for row in lesson_rows:
        ref = row.get("item_ref", "").strip()
        if ref and ref not in seen:
            seen.add(ref)
            item_refs.append(ref)

    return [
        process_learning_item(activity_ref, grade, chapter, lesson, ref, lesson_rows, learnosity_content)
        for ref in item_refs
    ]
