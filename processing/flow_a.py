"""Flow A — Learning Item Feedback (Spec §7). Rule-based, no external API."""
from __future__ import annotations

import re

from utils.helpers import normalize_name
from processing.scoring import (
    score_item_row, detect_divergences, rag_from_score,
)


def _ref_core(ref: str) -> str:
    """Normalised lesson-name core of a ref (alnum, lowercase, version tail cut).
    'US-G6-Find-...-Numbers-V3-1.W04' and its item '...-Numbers-V3-1-004' both
    reduce to 'usg6find...numbers'."""
    s = re.sub(r"[^a-z0-9]", "", (ref or "").lower())
    m = re.search(r"v3", s)          # cut at the version marker (V3-1 / V3.1 / …)
    return s[:m.start()] if m else s


def _core_similarity(a: str, b: str) -> float:
    """Common-prefix ratio of two name-cores (0..1)."""
    if not a or not b:
        return 1.0
    n = 0
    for x, y in zip(a, b):
        if x == y:
            n += 1
        else:
            break
    return n / max(len(a), len(b))


def _filter_stray_items(item_refs: list[str]) -> list[str]:
    """Drop an item whose name-core clearly differs from the lesson's OTHER
    items — i.e. a wrong-lesson item ref that merged-cell forward-fill attached
    here (e.g. a Prime-Factorization ref inside a Simplify-Expressions lesson).

    Compares items against each other (not the activity ref, whose format often
    differs), and only acts when there's a clear dominant name shared by ≥2
    items — so normal lessons are never touched.
    """
    if len(item_refs) < 3:
        return item_refs
    cores = [_ref_core(r) for r in item_refs]
    from collections import Counter
    dom, dom_n = Counter(c for c in cores if c).most_common(1)[0]
    if dom_n < 2:
        return item_refs  # no clear majority → don't risk dropping anything
    return [r for r, c in zip(item_refs, cores)
            if _core_similarity(c, dom) >= 0.5]


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

    # Dimensions score 2/3/5; anything below 5 (i.e. ≤3) is a noted concern.
    concerns = []
    if scores.get("understanding", 5) < 5:
        concerns.append("understanding gaps")
    if scores.get("engagement", 5) < 5:
        concerns.append("low engagement")
    if scores.get("examples", 5) < 5:
        concerns.append("insufficient examples")
    if scores.get("length", 5) < 5:
        concerns.append(f"length issue ({row.get('length','')})")
    if scores.get("language", 5) < 5:
        concerns.append("language/readability")

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

    # Per-dimension AVERAGES across teachers (Length is now a direct dimension).
    _dims = ["understanding", "engagement", "examples", "length", "language"]
    dim_avgs = {d: round(sum(s[d] for s in all_scores) / n_teachers, 1) for d in _dims}

    # Item score = mean of the 5 dimensions (average of the teachers' item scores).
    # No divergence penalty at item level (penalties are section-level, per spec).
    final_score = round(sum(s["item_score"] for s in all_scores) / n_teachers, 1)
    rating = rag_from_score(final_score)

    # Divergence is detected for INFO only (shown as "teachers differ"), no penalty.
    divergences = detect_divergences(all_scores)

    # Build per-teacher summaries
    teacher_summaries = {}
    for i, (row, scores) in enumerate(zip(teacher_rows, all_scores)):
        key = f"teacher{i+1}"
        teacher_summaries[key] = _teacher_summary(row, scores)

    # Structured breakdown for the UI "how this is calculated" panel.
    score_breakdown = {
        "teacher_count":       n_teachers,
        "dimension_averages":  dim_avgs,
        "final_score":         final_score,
        "rating":              rating,
        "diverging_dimensions": [d["dimension"] for d in divergences],
    }

    # Concise, accurate rationale (mean of the 5 dimensions; matches shown score).
    rationale = (
        f"{rating} — {final_score:.1f}/5, the average of 5 dimensions across "
        f"{n_teachers} teacher(s): understanding {dim_avgs['understanding']:.1f}, "
        f"engagement {dim_avgs['engagement']:.1f}, examples {dim_avgs['examples']:.1f}, "
        f"length {dim_avgs['length']:.1f}, language {dim_avgs['language']:.1f}. "
        f"Bands: Good ≥4.0, Average 2.5–3.9, Bad <2.5."
    )

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

    item_refs = _filter_stray_items(item_refs)

    return [
        process_learning_item(activity_ref, grade, chapter, lesson, ref, lesson_rows, learnosity_content)
        for ref in item_refs
    ]
