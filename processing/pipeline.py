"""Headless ingestion + scoring pipeline.

Shared by the Streamlit app (app.py) and the one-shot recompute tool
(_recompute.py). No Streamlit dependency — progress and warnings go through
optional callbacks so the same code runs in a browser session or on the server.
"""
from __future__ import annotations

import concurrent.futures

from data.sheets_reader import fetch_all_lesson_reviews, fetch_error_reports
from data.classroom_reader import fetch_classroom_reviews, match_classroom_to_lessons
from data.lookup_reader import fetch_lesson_lookup
from data.exit_ticket_reader import fetch_exit_ticket_scores
from data.learnosity_client import _fetch_from_supabase, _fallback
from processing.flow_a import run_flow_a
from processing.flow_b import run_flow_b, _BACKFILL_FIELDS
from processing.errors import collect_lesson_errors
from processing.ai_expert_review import get_cached_ai_score
from utils.deduplication import (
    deduplicate_reviews, group_by_lesson,
    get_reviewers_with_feedback, group_errors_by_lesson,
)
from utils.cache import (
    compute_hash, all_hashes, all_results as load_all_results,
    get_all_learnosity_content, bulk_store_learnosity_content,
    store_hashes, save_all_results,
)
from utils.helpers import normalize_name

# Bump when scoring/gating logic changes so cached results recompute on refresh.
# v13: exit-ticket student data now feeds the 10% component (exit_ticket_reader),
# matched to lessons by learnosity_activity_ref == Activity Reference ID.
_LOGIC_VERSION = "v13"


def run_pipeline(force: bool = False, progress=None, warn=None) -> dict:
    """Full ingestion + scoring. `progress(pct:int, text:str)` and `warn(msg:str)`
    are optional callbacks. Returns the full results dict and persists it."""
    _p = progress or (lambda pct, text="": None)
    _w = warn or (lambda msg: print(f"[pipeline] {msg}"))

    def _try(fn, default):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return default if not isinstance(default, Exception) else exc

    _p(5, "Fetching data sources in parallel…")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        f_sheets    = pool.submit(_try, fetch_all_lesson_reviews, RuntimeError("sheets"))
        f_errors    = pool.submit(_try, fetch_error_reports, [])
        f_classroom = pool.submit(_try, fetch_classroom_reviews, [])
        f_lookup    = pool.submit(_try, fetch_lesson_lookup, {})
        f_exit      = pool.submit(_try, fetch_exit_ticket_scores, {})
        raw_rows          = f_sheets.result()
        error_records     = f_errors.result()
        classroom_records = f_classroom.result()
        lesson_lookup     = f_lookup.result()
        exit_scores       = f_exit.result()
    if not isinstance(exit_scores, dict):
        exit_scores = {}

    if isinstance(raw_rows, Exception) or not isinstance(raw_rows, list):
        _w(f"Failed to read Google Sheets: {raw_rows}")
        return load_all_results()

    _p(20, "Deduplicating reviews…")
    clean_rows = deduplicate_reviews(raw_rows)
    lessons    = group_by_lesson(clean_rows)
    classroom_by_lesson = match_classroom_to_lessons(classroom_records or [], lessons.keys())
    errors_by_lesson    = group_errors_by_lesson(error_records if isinstance(error_records, list) else [])

    # Learnosity content cache (item-list for AI item refs; not health-critical).
    learnosity_cache: dict = get_all_learnosity_content()
    missing_refs = [ref for ref in lessons if force or ref not in learnosity_cache]
    if missing_refs:
        _p(25, f"Fetching {len(missing_refs)} lesson(s) content…")

        def _sb(ref):
            return ref, _fetch_from_supabase(ref) or _fallback(ref)

        new_content: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futures = {pool.submit(_sb, ref): ref for ref in missing_refs}
            done = 0
            for fut in concurrent.futures.as_completed(futures):
                ref, content = fut.result()
                new_content[ref] = content
                learnosity_cache[ref] = content
                done += 1
                _p(25 + int(done / len(missing_refs) * 20), f"Content: {done}/{len(missing_refs)}…")
        bulk_store_learnosity_content(new_content)

    # ── Process lessons ───────────────────────────────────────────────────────
    total = len(lessons)
    results: dict = {}
    new_results: dict = {}
    new_hashes: dict = {}
    stored_results = load_all_results()
    stored_hashes  = all_hashes()

    for i, (activity_ref, lesson_rows) in enumerate(lessons.items()):
        _p(45 + int((i / max(total, 1)) * 50), f"Scoring {i+1}/{total}…")

        completed_reviews = get_reviewers_with_feedback(lesson_rows)
        classroom     = classroom_by_lesson.get(activity_ref, [])
        lesson_errors = errors_by_lesson.get(activity_ref, [])

        if lesson_lookup and activity_ref in lesson_lookup:
            meta = lesson_lookup[activity_ref]
            for row in lesson_rows:
                row["grade"]   = row.get("grade")   or meta["grade"]
                row["chapter"] = row.get("chapter") or meta["chapter"]
                row["lesson"]  = row.get("lesson")  or meta["lesson"]

        g = lesson_rows[0].get("grade", "") if lesson_rows else ""
        c = lesson_rows[0].get("chapter", "") if lesson_rows else ""
        l = lesson_rows[0].get("lesson", "") if lesson_rows else ""

        # Completeness gate — Pending until 3 reviewers submitted real feedback.
        if len(completed_reviews) < 3:
            results[activity_ref] = {
                "activity_ref": activity_ref, "grade": g, "chapter": c, "lesson": l,
                "status": "Pending", "final_rating": "Pending",
                "teacher_names": completed_reviews, "weighted_score": 0.0,
                "health": {"score": 0.0, "rating": "Pending", "components": {}, "weights": {}},
                "one_line_summary": f"Awaiting {3 - len(completed_reviews)} more review(s).",
                "section_ratings": {}, "flow_a_results": [],
                "error_reports": lesson_errors,
                "detected_errors": collect_lesson_errors(activity_ref, g, c, l, lesson_rows, lesson_errors),
            }
            continue

        ai_score  = get_cached_ai_score(activity_ref)
        exit_info = exit_scores.get(activity_ref)
        exit_score = (exit_info or {}).get("score_5")
        combined_hash = compute_hash({"rows": lesson_rows, "classroom": classroom,
                                      "errors": lesson_errors, "ai": ai_score,
                                      "exit": exit_score, "logic": _LOGIC_VERSION})
        if not force and stored_hashes.get(activity_ref) == combined_hash:
            cached = stored_results.get(activity_ref)
            if cached:
                results[activity_ref] = cached
                continue

        learnosity_content = learnosity_cache.get(
            activity_ref,
            {"activity_ref": activity_ref, "source": "unavailable", "items": []},
        )

        try:
            flow_a_results = run_flow_a(activity_ref, lesson_rows, learnosity_content,
                                        error_reports=lesson_errors)
        except Exception as exc:  # noqa: BLE001
            _w(f"Flow A failed for {activity_ref}: {exc}")
            flow_a_results = []

        try:
            result = run_flow_b(activity_ref, lesson_rows, flow_a_results, classroom,
                                learnosity_content, error_reports=lesson_errors,
                                ai_score=ai_score, exit_data_score=exit_score)
        except Exception as exc:  # noqa: BLE001
            _w(f"Flow B failed for {activity_ref}: {exc}")
            result = {"activity_ref": activity_ref, "final_rating": "Average", "error": str(exc)}

        result["exit_data"]      = exit_info            # {pct, score_5, n_items, n_widgets} or None
        result["status"]         = "Complete"
        result["review_date"]    = lesson_rows[0].get("review_date", "")
        result["error_reports"]  = lesson_errors
        result["detected_errors"] = collect_lesson_errors(
            activity_ref, result.get("grade", ""), result.get("chapter", ""),
            result.get("lesson", ""), lesson_rows, lesson_errors)

        # Attach per-teacher raw data (for AI review generation)
        teachers_data: list = []
        seen: set[str] = set()
        for row in lesson_rows:
            norm = normalize_name(row.get("reviewer_name", ""))
            if norm and norm not in seen:
                seen.add(norm)
                teachers_data.append(dict(row))
        for tr in teachers_data:
            norm = normalize_name(tr.get("reviewer_name", ""))
            for field in _BACKFILL_FIELDS:
                if not (tr.get(field) or "").strip():
                    for row in lesson_rows:
                        if (normalize_name(row.get("reviewer_name", "")) == norm
                                and (row.get(field) or "").strip()):
                            tr[field] = row[field]
                            break
        result["_per_teacher_data"] = teachers_data[:3]

        new_results[activity_ref] = result
        new_hashes[activity_ref]  = combined_hash
        results[activity_ref]     = result

    if new_hashes:
        store_hashes(new_hashes)
    save_all_results(results)
    _p(100, "Done.")
    return results
