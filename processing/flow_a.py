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

    if len(teacher_rows) < 3:
        # Show whatever partial data exists so the UI isn't empty
        partial_scores = [score_item_row(row) for row in teacher_rows]
        partial_summaries = {
            f"teacher{i+1}": _teacher_summary(row, scores)
            for i, (row, scores) in enumerate(zip(teacher_rows, partial_scores))
        }
        return {
            "item_ref": item_ref,
            "section": "Learning",
            "rating": "Pending",
            "rationale": (
                f"Awaiting {3 - len(teacher_rows)} more review(s) to compute a final rating. "
                + (f"Partial data from {len(teacher_rows)} teacher(s) shown below." if teacher_rows else "")
            ),
            "teacher_summaries": partial_summaries,
            "divergences": [],
            "ai_expert_review": {},
            "score": 0.0,
        }

    # Score each teacher's row
    all_scores = [score_item_row(row) for row in teacher_rows]
    avg_score = round(sum(s["item_score"] for s in all_scores) / len(all_scores), 2)

    # Detect divergences
    divergences = detect_divergences(all_scores)

    # Divergence penalty: each diverging dimension reduces score slightly
    penalty = len(divergences) * 0.2
    final_score = max(1.0, avg_score - penalty)
    rating = rag_from_score(final_score)

    # Build per-teacher summaries
    teacher_summaries = {}
    for i, (row, scores) in enumerate(zip(teacher_rows, all_scores)):
        key = f"teacher{i+1}"
        teacher_summaries[key] = _teacher_summary(row, scores)

    # Build rationale
    score_parts = [
        f"understanding {all_scores[0].get('understanding',3):.1f}",
        f"engagement {all_scores[0].get('engagement',3):.1f}",
        f"examples {all_scores[0].get('examples',3):.1f}",
        f"language {all_scores[0].get('language',3):.1f}",
    ]
    rationale = (
        f"Average item score: {avg_score:.1f}/5 across 3 teachers "
        f"({', '.join(score_parts)}). "
    )
    if divergences:
        rationale += f"{len(divergences)} divergence(s) flagged: " + \
                     "; ".join(d["dimension"] for d in divergences) + "."
    if penalty:
        rationale += f" Divergence penalty applied (−{penalty:.1f})."

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
        "score": round(final_score, 2),
        "rating": rating,
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
