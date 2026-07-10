"""
Cuemath Curriculum Efficacy Dashboard
Run: python -m streamlit run app.py --server.headless true
"""
from __future__ import annotations

import concurrent.futures
import time
from datetime import datetime, date

import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Cuemath · Curriculum Efficacy",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports after page config ──────────────────────────────────────────────────
from config.settings import LESSON_REVIEW_XLSX_URL, CLASSROOM_ADMIN_URL
from data.sheets_reader import fetch_all_lesson_reviews, fetch_error_reports
from data.classroom_reader import fetch_classroom_reviews, group_classroom_by_lesson
from data.lookup_reader import fetch_lesson_lookup
from data.learnosity_client import get_lesson_content
from processing.flow_a import run_flow_a
from processing.flow_b import run_flow_b
from utils.deduplication import (
    deduplicate_reviews,
    group_by_lesson,
    get_unique_teachers,
    get_reviewers_with_feedback,
    group_errors_by_lesson,
)
from utils.cache import (
    compute_hash, has_changed, all_hashes,
    get_result, all_results as load_all_results,
    get_all_learnosity_content, bulk_store_learnosity_content,
    store_hashes, save_all_results,
)
from utils.helpers import safe_float
from dashboard.master_view import render_master_view
from dashboard.detail_view import render_detail_view
from dashboard.theme import inject_theme
from export.pdf_export import generate_pdf
from utils.auth import auto_auth_available, get_effective_auth_token

# ── Inject Cuemath design system ──────────────────────────────────────────────
inject_theme()


# ── Credential check helper ───────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _check_credentials() -> list[str]:
    """Check that the two data sources are reachable. Cached 5 min."""
    issues = []
    try:
        import requests
        r = requests.head(LESSON_REVIEW_XLSX_URL, timeout=8, allow_redirects=True)
        if r.status_code >= 400:
            issues.append(f"Lesson Review Sheet not accessible (HTTP {r.status_code}).")
    except Exception as exc:
        issues.append(f"Cannot reach Lesson Review Sheet: {exc}")
    return issues


# Bump this when scoring/gating logic changes so cached results are recomputed
# on the next refresh (no force needed). v6: new rating logic per ratings.txt —
# 5 direct dimension scores (Length is a score, not a multiplier), section
# averages, weights Learning40/Practice20/Exit5/Overall10/Classroom25 (rescaled
# if a section is missing), targeted −0.2 penalties, no divergence penalty.
_LOGIC_VERSION = "v9"


# ── Core pipeline ─────────────────────────────────────────────────────────────
def process_all_lessons(force: bool = False) -> dict:
    """Full ingestion + processing pipeline. Returns dict of all results."""
    from utils.helpers import normalize_name
    from processing.flow_b import _BACKFILL_FIELDS
    from data.learnosity_client import _fetch_from_supabase, _fallback
    from processing.ai_expert_review import generate_ai_expert_review
    from data.ai_review_reader import fetch_ai_reviews as _fetch_ai_doc_reviews

    progress = st.progress(0, text="Fetching lesson reviews from Google Sheets…")

    # ── 1. Parallel network fetches ──────────────────────────────────────────
    def _fetch_sheets():
        try:
            return fetch_all_lesson_reviews()
        except Exception as exc:
            return exc

    def _fetch_errors():
        try:
            return fetch_error_reports()
        except Exception:
            return []

    def _fetch_classroom():
        try:
            return fetch_classroom_reviews()
        except Exception:
            return []

    def _fetch_lookup():
        try:
            return fetch_lesson_lookup()
        except Exception:
            return {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        f_sheets    = pool.submit(_fetch_sheets)
        f_errors    = pool.submit(_fetch_errors)
        f_classroom = pool.submit(_fetch_classroom)
        f_lookup    = pool.submit(_fetch_lookup)
        progress.progress(5, text="Fetching data sources in parallel…")
        raw_rows          = f_sheets.result()
        error_records     = f_errors.result()
        classroom_records = f_classroom.result()
        lesson_lookup     = f_lookup.result()

    if isinstance(raw_rows, Exception):
        st.error(f"Failed to read Google Sheets: {raw_rows}")
        return load_all_results()
    if isinstance(classroom_records, Exception):
        st.warning(f"Classroom reviews unavailable: {classroom_records}")
        classroom_records = []

    progress.progress(20, text="Deduplicating reviews…")
    clean_rows = deduplicate_reviews(raw_rows)
    lessons    = group_by_lesson(clean_rows)
    classroom_by_lesson = group_classroom_by_lesson(classroom_records)
    errors_by_lesson    = group_errors_by_lesson(
        error_records if isinstance(error_records, list) else []
    )

    # ── 2. Pre-load Learnosity cache, parallel-fetch any missing entries ──────
    learnosity_cache: dict = get_all_learnosity_content()
    # Only fetch content we've NEVER looked up. Previously we also re-fetched every
    # ref cached as "unavailable" — i.e. all of them, every refresh (~40s wasted),
    # since the sheet's activity refs don't match Supabase. A force refresh still
    # retries everything (including unavailable) below.
    missing_refs = [
        ref for ref in lessons
        if force or ref not in learnosity_cache
    ]

    if missing_refs:
        progress.progress(25, text=f"Fetching {len(missing_refs)} lesson(s) from Supabase…")

        def _supabase_fetch(ref: str):
            return ref, _fetch_from_supabase(ref) or _fallback(ref)

        new_content: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futures = {pool.submit(_supabase_fetch, ref): ref for ref in missing_refs}
            done = 0
            for future in concurrent.futures.as_completed(futures):
                ref, content = future.result()
                new_content[ref] = content
                learnosity_cache[ref] = content
                done += 1
                pct = 25 + int(done / len(missing_refs) * 20)
                progress.progress(pct, text=f"Supabase: {done}/{len(missing_refs)} fetched…")

        bulk_store_learnosity_content(new_content)
    else:
        progress.progress(45, text="Lesson content loaded from cache…")

    # ── 3. Process lessons ────────────────────────────────────────────────────
    total = len(lessons)
    results: dict   = {}
    new_results: dict  = {}
    new_hashes: dict   = {}

    # Load the result + hash caches ONCE (previously re-read from disk per lesson,
    # i.e. 217× parsing of a ~1 MB JSON — a big, silent cost on every refresh).
    stored_results = load_all_results()
    stored_hashes  = all_hashes()

    for i, (activity_ref, lesson_rows) in enumerate(lessons.items()):
        pct = 45 + int((i / max(total, 1)) * 50)
        progress.progress(pct, text=f"Scoring {i+1}/{total}…")

        unique_teachers   = get_unique_teachers(lesson_rows)
        completed_reviews = get_reviewers_with_feedback(lesson_rows)
        classroom         = classroom_by_lesson.get(activity_ref, [])
        lesson_errors     = errors_by_lesson.get(activity_ref, [])

        # Backfill grade / chapter / lesson from lookup
        if lesson_lookup and activity_ref in lesson_lookup:
            meta = lesson_lookup[activity_ref]
            for row in lesson_rows:
                if not row.get("grade"):   row["grade"]   = meta["grade"]
                if not row.get("chapter"): row["chapter"] = meta["chapter"]
                if not row.get("lesson"):  row["lesson"]  = meta["lesson"]

        # Completeness gate — a lesson is Pending until 3 reviewers have actually
        # submitted feedback. Error-report rows and blank stubs carry a reviewer
        # name but no feedback, so they must NOT count toward the 3.
        if len(completed_reviews) < 3:
            results[activity_ref] = {
                "activity_ref": activity_ref,
                "grade":    lesson_rows[0].get("grade", "") if lesson_rows else "",
                "chapter":  lesson_rows[0].get("chapter", "") if lesson_rows else "",
                "lesson":   lesson_rows[0].get("lesson", "") if lesson_rows else "",
                "status":   "Pending",
                "teacher_names":    completed_reviews,
                "teacher_ratings":  [],
                "avg_teacher_rating": 0.0,
                "final_rating":     "Pending",
                "one_line_summary": f"Awaiting {3 - len(completed_reviews)} more review(s).",
                "section_ratings":  {},
                "flow_a_results":   [],
                "actionable_recommendations": [],
                "error_reports":    lesson_errors,
            }
            continue

        # Change detection. `logic` invalidates all cached results when the scoring
        # logic changes (bump _LOGIC_VERSION) so fixes apply without a force refresh.
        combined_hash = compute_hash({"rows": lesson_rows, "classroom": classroom,
                                      "errors": lesson_errors, "logic": _LOGIC_VERSION})
        if not force and stored_hashes.get(activity_ref) == combined_hash:
            cached = stored_results.get(activity_ref)
            if cached:
                results[activity_ref] = cached
                continue

        learnosity_content = learnosity_cache.get(
            activity_ref,
            {"activity_ref": activity_ref, "source": "unavailable", "items": [], "note": "Content unavailable."},
        )

        # Flow A
        try:
            flow_a_results = run_flow_a(activity_ref, lesson_rows, learnosity_content)
        except Exception as exc:
            st.warning(f"Flow A failed for {activity_ref}: {exc}")
            flow_a_results = []

        # Flow B
        try:
            flow_b_result = run_flow_b(
                activity_ref, lesson_rows, flow_a_results, classroom, learnosity_content,
                error_reports=lesson_errors,
            )
        except Exception as exc:
            st.warning(f"Flow B failed for {activity_ref}: {exc}")
            flow_b_result = {"activity_ref": activity_ref, "final_rating": "Average", "error": str(exc)}

        # Lesson is Complete once 3 teachers have reviewed it (the gate above).
        # Individual items are rated from whatever reviews each has.
        flow_b_result["status"]        = "Complete"
        flow_b_result["review_date"]   = lesson_rows[0].get("review_date", "")
        flow_b_result["error_reports"] = lesson_errors

        # Attach per-teacher raw data
        teachers_data: list = []
        seen_norms: set[str] = set()
        for row in lesson_rows:
            norm = normalize_name(row.get("reviewer_name", ""))
            if norm and norm not in seen_norms:
                seen_norms.add(norm)
                teachers_data.append(dict(row))
        for teacher_row in teachers_data:
            norm = normalize_name(teacher_row.get("reviewer_name", ""))
            for field in _BACKFILL_FIELDS:
                if not (teacher_row.get(field) or "").strip():
                    for row in lesson_rows:
                        if (normalize_name(row.get("reviewer_name", "")) == norm
                                and (row.get(field) or "").strip()):
                            teacher_row[field] = row[field]
                            break
        flow_b_result["_per_teacher_data"] = teachers_data[:3]

        new_results[activity_ref] = flow_b_result
        new_hashes[activity_ref]  = combined_hash
        results[activity_ref]     = flow_b_result

    # ── 4. Persist results + hashes ──────────────────────────────────────────
    # Store change-detection hashes for the freshly computed lessons, then
    # overwrite the whole results cache with the CURRENT state (Complete AND
    # Pending). This prunes stale entries — e.g. a lesson that was Complete but is
    # now Pending (lost a reviewer) no longer lingers as an old Complete result.
    if new_hashes:
        store_hashes(new_hashes)
    save_all_results(results)

    # ── 5. AI Expert Reviews are generated LAZILY (on lesson open) ────────────
    # Each review is a ~10-25s LLM call; generating all Complete lessons here made
    # refresh take 3-5 min. Instead the detail view generates a lesson's review on
    # first open (with a spinner) and caches it — so refresh stays fast (~10s) and
    # the master list (which uses the rule-based rating) is unaffected.

    progress.progress(100, text="Done.")
    time.sleep(0.2)
    progress.empty()
    return results


# ── Sidebar ────────────────────────────────────────────────────────────────────
def render_sidebar(results: dict) -> None:
    from dashboard.theme import sidebar_brand
    with st.sidebar:
        sidebar_brand()

        last_refresh = st.session_state.get("last_refresh")
        if last_refresh:
            st.caption(f"Refreshed {last_refresh}")
        else:
            st.caption("Not yet refreshed this session")

        if st.button("🔄  Refresh Data", use_container_width=True, type="primary"):
            with st.spinner("Pulling latest data…"):
                st.session_state["results"] = process_all_lessons(force=False)
                st.session_state["last_refresh"] = datetime.now().strftime("%d %b %Y, %H:%M")
                st.session_state.pop("selected_lesson", None)
            st.rerun()

        st.divider()

        # ── PDF Export ─────────────────────────────────────────────────────────
        st.markdown("### Export")
        from_d = st.date_input("From date", value=None, key="pdf_from")
        to_d   = st.date_input("To date",   value=None, key="pdf_to")

        grade_opts = ["All"] + sorted({r.get("grade", "") for r in results.values() if r.get("grade")})
        grade_sel  = st.selectbox("Grade", grade_opts, key="pdf_grade")

        chap_source = results.values() if grade_sel == "All" else [
            r for r in results.values() if r.get("grade") == grade_sel
        ]
        chap_opts = ["All"] + sorted({r.get("chapter", "") for r in chap_source if r.get("chapter")})
        chap_sel  = st.selectbox("Chapter", chap_opts, key="pdf_chapter")

        all_teachers = sorted({
            n for r in results.values() for n in (r.get("teacher_names") or []) if n
        })
        teacher_opts = ["All"] + all_teachers
        teacher_sel  = st.selectbox("Teacher", teacher_opts, key="pdf_teacher")

        rag_sel       = st.selectbox("RAG status", ["All", "Good", "Average", "Bad"], key="pdf_rag")
        teacher_mode  = st.checkbox("Teacher summary mode", value=False, key="pdf_teacher_mode",
                                    help="Generate a teacher-centric report instead of a lesson report")
        include_detail = st.checkbox("Include detail pages", value=False, key="pdf_detail")

        if st.button("Generate PDF", use_container_width=True):
            if not results:
                st.warning("No data to export — refresh first.")
            elif teacher_mode and teacher_sel == "All":
                st.warning("Select a specific teacher for teacher summary mode.")
            else:
                with st.spinner("Generating PDF…"):
                    pdf_bytes = generate_pdf(
                        results,
                        from_date=from_d if from_d else None,
                        to_date=to_d if to_d else None,
                        grade_filter=grade_sel,
                        chapter_filter=chap_sel,
                        teacher_filter=teacher_sel,
                        rag_filter=rag_sel,
                        include_detail_pages=include_detail,
                        teacher_summary_mode=teacher_mode,
                    )
                from_str = str(from_d or "all")
                to_str   = str(to_d or "all")
                t_tag    = f"_{teacher_sel}" if teacher_sel != "All" else ""
                filename = f"Efficacy_Report{t_tag}_{from_str}_to_{to_str}.pdf"
                st.download_button(
                    label="Download PDF",
                    data=pdf_bytes,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                )

        st.divider()

        # ── Learnosity Integration ─────────────────────────────────────────────
        st.markdown("### Learnosity")
        if auto_auth_available():
            token = get_effective_auth_token()
            if token:
                st.success("✅ Auto-authenticated via Railway credentials")
            else:
                st.error("⚠️ Auto-login failed — check SUPABASE_DASHBOARD_EMAIL / PASSWORD env vars")
        else:
            st.text_input(
                "Auth Token",
                type="password",
                key="railway_auth_token",
                placeholder="Paste Bearer token from Michelangelo Studio…",
                help=(
                    "Open Michelangelo Studio → F12 → Console tab → paste:\n"
                    "JSON.parse(localStorage.getItem(Object.keys(localStorage)"
                    ".find(k=>k.startsWith('sb-')))).access_token"
                ),
            )
            if st.session_state.get("railway_auth_token"):
                st.caption("✅ Token set — items will be fetched from Learnosity")
            else:
                st.caption("No token — showing reviewed items only")

        st.divider()

        # ── System status ──────────────────────────────────────────────────────
        st.markdown("### System")
        issues = _check_credentials()
        if issues:
            for issue in issues:
                st.error(f"⚠ {issue}")
        else:
            st.success("Data sources reachable")
        st.caption("Learnosity API: active when token provided")


# ── Main app ──────────────────────────────────────────────────────────────────
def main() -> None:
    # Load cached results on first render (no API calls on startup)
    if "results" not in st.session_state:
        st.session_state["results"] = load_all_results()

    results = st.session_state["results"]
    render_sidebar(results)

    # ── Header ────────────────────────────────────────────────────────────────
    col1, col2 = st.columns([5, 1])
    with col1:
        st.markdown(
            """
            <h1 style="margin-bottom:2px">Curriculum Efficacy Dashboard</h1>
            <p style="color:#5B6B82;font-size:0.9rem;margin:0">
              Lesson review consolidation · Flow A + B pipeline
            </p>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        last = st.session_state.get("last_refresh", "Not yet refreshed")
        st.markdown(
            f'<div style="text-align:right;padding-top:8px;">'
            f'<div style="font-size:0.72rem;color:#5B6B82;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:0.07em;">Last refresh</div>'
            f'<div style="font-size:0.85rem;font-weight:700;color:#0E1B3D;">{last}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if not results:
        st.markdown(
            """
            <div style="
              background:#FFFFFF;border-radius:14px;
              padding:2rem 2.5rem;margin:1.5rem 0;
              border:1px solid #E4EAF3;
              box-shadow:0 1px 4px rgba(14,27,61,0.05);
            ">
              <div style="font-size:2rem;margin-bottom:0.75rem">📐</div>
              <h3 style="margin-bottom:6px">Ready to review</h3>
              <p style="color:#5B6B82;margin:0">
                Click <strong>Refresh Data</strong> in the sidebar to pull the latest
                lesson reviews from Google Sheets and run the scoring pipeline.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        issues = _check_credentials()
        if issues:
            with st.expander("Data source issue", expanded=True):
                for issue in issues:
                    st.error(issue)
        return

    # ── Navigate between master and detail views ───────────────────────────────
    if "selected_lesson" in st.session_state:
        activity_ref = st.session_state["selected_lesson"]
        lesson_result = results.get(activity_ref)
        if lesson_result:
            render_detail_view(lesson_result)
        else:
            st.error(f"Lesson '{activity_ref}' not found in results.")
            if st.button("← Back"):
                del st.session_state["selected_lesson"]
                st.rerun()
    else:
        def on_select(ref: str) -> None:
            st.session_state["selected_lesson"] = ref
            st.rerun()

        render_master_view(results, on_select_lesson=on_select)


if __name__ == "__main__":
    main()
