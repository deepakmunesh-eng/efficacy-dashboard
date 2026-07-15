"""
Cuemath Curriculum Efficacy Dashboard (4-component health model, 2026-07-13).
Run: python -m streamlit run app.py --server.headless true

Health of a lesson = Teacher Sheet 40% · Class review 30% · Exit-ticket data 10%
· AI review 20% (missing components rescaled out). Rolls up lesson→chapter→grade.
Errors are tracked separately and do NOT affect health.
"""
from __future__ import annotations

import concurrent.futures
import time
from datetime import datetime

import streamlit as st

st.set_page_config(
    page_title="Cuemath · Curriculum Efficacy",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

from config.settings import LESSON_REVIEW_XLSX_URL
from data.sheets_reader import fetch_all_lesson_reviews, fetch_error_reports
from data.classroom_reader import fetch_classroom_reviews, group_classroom_by_lesson
from data.lookup_reader import fetch_lesson_lookup
from processing.flow_a import run_flow_a
from processing.flow_b import run_flow_b, _BACKFILL_FIELDS
from processing.health import compute_health
from processing.errors import collect_lesson_errors
from utils.deduplication import (
    deduplicate_reviews, group_by_lesson,
    get_unique_teachers, get_reviewers_with_feedback, group_errors_by_lesson,
)
from utils.cache import (
    compute_hash, all_hashes, all_results as load_all_results,
    get_all_learnosity_content, bulk_store_learnosity_content,
    store_hashes, save_all_results,
)
from utils.helpers import normalize_name
from dashboard import simple_view

# Bump when scoring/gating logic changes so cached results recompute on refresh.
# v12: NEW 4-component health (Teacher40/Class30/ExitData10/AI20), errors no
# longer penalise health, AI review emits a 1-5 score folded into health.
_LOGIC_VERSION = "v12"


# ── Core pipeline ─────────────────────────────────────────────────────────────
def process_all_lessons(force: bool = False) -> dict:
    from data.learnosity_client import _fetch_from_supabase, _fallback
    from processing.ai_expert_review import get_cached_ai_score

    progress = st.progress(0, text="Fetching lesson reviews…")

    def _try(fn, default):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return default if not isinstance(default, Exception) else exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        f_sheets    = pool.submit(_try, fetch_all_lesson_reviews, RuntimeError("sheets"))
        f_errors    = pool.submit(_try, fetch_error_reports, [])
        f_classroom = pool.submit(_try, fetch_classroom_reviews, [])
        f_lookup    = pool.submit(_try, fetch_lesson_lookup, {})
        progress.progress(5, text="Fetching data sources in parallel…")
        raw_rows          = f_sheets.result()
        error_records     = f_errors.result()
        classroom_records = f_classroom.result()
        lesson_lookup     = f_lookup.result()

    if isinstance(raw_rows, Exception) or not isinstance(raw_rows, list):
        st.error(f"Failed to read Google Sheets: {raw_rows}")
        progress.empty()
        return load_all_results()

    progress.progress(20, text="Deduplicating reviews…")
    clean_rows = deduplicate_reviews(raw_rows)
    lessons    = group_by_lesson(clean_rows)
    classroom_by_lesson = group_classroom_by_lesson(classroom_records or [])
    errors_by_lesson    = group_errors_by_lesson(error_records if isinstance(error_records, list) else [])

    # Learnosity content cache (item-list for AI item refs; not health-critical).
    learnosity_cache: dict = get_all_learnosity_content()
    missing_refs = [ref for ref in lessons if force or ref not in learnosity_cache]
    if missing_refs:
        progress.progress(25, text=f"Fetching {len(missing_refs)} lesson(s) content…")

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
                progress.progress(25 + int(done / len(missing_refs) * 20),
                                  text=f"Content: {done}/{len(missing_refs)}…")
        bulk_store_learnosity_content(new_content)

    # ── Process lessons ───────────────────────────────────────────────────────
    total = len(lessons)
    results: dict = {}
    new_results: dict = {}
    new_hashes: dict = {}
    stored_results = load_all_results()
    stored_hashes  = all_hashes()

    for i, (activity_ref, lesson_rows) in enumerate(lessons.items()):
        progress.progress(45 + int((i / max(total, 1)) * 50), text=f"Scoring {i+1}/{total}…")

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

        ai_score = get_cached_ai_score(activity_ref)
        combined_hash = compute_hash({"rows": lesson_rows, "classroom": classroom,
                                      "errors": lesson_errors, "ai": ai_score,
                                      "logic": _LOGIC_VERSION})
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
            st.warning(f"Flow A failed for {activity_ref}: {exc}")
            flow_a_results = []

        try:
            result = run_flow_b(activity_ref, lesson_rows, flow_a_results, classroom,
                                learnosity_content, error_reports=lesson_errors,
                                ai_score=ai_score)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Flow B failed for {activity_ref}: {exc}")
            result = {"activity_ref": activity_ref, "final_rating": "Average", "error": str(exc)}

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

    progress.progress(100, text="Done.")
    time.sleep(0.15)
    progress.empty()
    return results


# ── AI review generation (lazy, on lesson open) ────────────────────────────────
def generate_ai_for_lesson(activity_ref: str) -> dict:
    """Generate + cache the AI review, store it in session, and fold its 1-5 score
    into that lesson's health immediately."""
    from processing.ai_expert_review import generate_ai_expert_review
    from data.ai_review_reader import fetch_ai_reviews

    results = st.session_state.get("results", {})
    result = results.get(activity_ref)
    if not result:
        return {"error": "Lesson not found"}

    try:
        ai_doc = fetch_ai_reviews()
    except Exception:
        ai_doc = {}

    ai = generate_ai_expert_review(result, result.get("flow_a_results", []), ai_doc)
    st.session_state.setdefault("ai_reviews", {})[activity_ref] = ai

    # Fold AI score into health (recompute the 4-component blend).
    ai_score = ai.get("ai_score") if not ai.get("error") else None
    if ai_score is not None:
        classroom = result.get("section_ratings", {}).get("classroom_review", {}).get("score") or None
        health = compute_health(
            teacher=result.get("teacher_score") or None,
            classroom=classroom,
            exit_data=None,
            ai=ai_score,
        )
        result["health"] = health
        result["weighted_score"] = health["score"]
        result["final_rating"] = health["rating"]
        save_all_results(results)
    return ai


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    if "results" not in st.session_state:
        st.session_state["results"] = load_all_results()
    st.session_state.setdefault("nav", {})
    st.session_state.setdefault("ai_reviews", {})
    st.session_state.setdefault("view_mode", "🩺 Health")

    def nav(home=False, grade=None, chapter=None, lesson=None):
        if home:
            st.session_state["nav"] = {}
        else:
            nn = {}
            if grade:   nn["grade"] = grade
            if chapter: nn["chapter"] = chapter
            if lesson:  nn["lesson"] = lesson
            st.session_state["nav"] = nn
        st.rerun()

    # ── Sidebar: Refresh · View selector · Grades ─────────────────────────────
    with st.sidebar:
        st.markdown("### 📐 Efficacy Dashboard")
        last = st.session_state.get("last_refresh")
        st.caption(f"Refreshed {last}" if last else "Not yet refreshed this session")

        if st.button("🔄  Refresh Data", use_container_width=True, type="primary"):
            with st.spinner("Pulling latest data…"):
                st.session_state["results"] = process_all_lessons(force=False)
                st.session_state["last_refresh"] = datetime.now().strftime("%d %b %Y, %H:%M")
                st.session_state["nav"] = {}
            st.rerun()

        st.divider()
        view = st.radio("View", ["🩺 Health", "🚩 Errors reported"], key="view_mode",
                        label_visibility="collapsed")
        mode = "errors" if "Errors" in view else "health"

        st.divider()
        results = st.session_state.get("results", {})
        if results:
            simple_view.render_grade_nav(results, nav)

        st.divider()
        complete = [r for r in results.values() if r.get("status") == "Complete"]
        st.caption(f"{len(complete)} complete · {len(results) - len(complete)} pending")

        from config.settings import AI_REVIEW_ENABLED
        if AI_REVIEW_ENABLED:
            if st.button("✨ Generate all AI reviews", use_container_width=True):
                todo = [r["activity_ref"] for r in complete
                        if r["activity_ref"] not in st.session_state.get("ai_reviews", {})]
                prog = st.progress(0, text=f"0/{len(todo)}")
                for i, ref in enumerate(todo):
                    generate_ai_for_lesson(ref)
                    prog.progress((i + 1) / max(len(todo), 1), text=f"{i+1}/{len(todo)}")
                prog.empty()
                st.rerun()
        else:
            st.caption("🔒 AI review (20%) on hold until Learnosity access "
                       "(`AI_REVIEW_ENABLED=1`).")

    # ── Main area (full width) ────────────────────────────────────────────────
    title = "🚩 Errors Reported" if mode == "errors" else "Curriculum Efficacy Dashboard"
    st.markdown(f"# {title}")
    if mode == "health":
        st.caption("Health = Teacher 40% · Class 30% · Exit-data 10% · AI 20% "
                   "(missing rescaled). Good ≥4.0 · Average 2.5–3.9 · Bad <2.5.")
    else:
        st.caption("Errors are tracked separately and do **not** affect health.")

    if not results:
        st.info("No data yet — click **Refresh Data** in the sidebar to pull the "
                "latest lesson reviews and run the scoring pipeline.")
        return

    simple_view.render_content(results, nav, generate_ai_for_lesson, mode)


if __name__ == "__main__":
    main()
