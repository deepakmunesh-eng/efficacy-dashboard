"""
Cuemath Curriculum Efficacy Dashboard (4-component health model, 2026-07-13).
Run: python -m streamlit run app.py --server.headless true

Health of a lesson = Teacher Sheet 40% · Class review 30% · Exit-ticket data 10%
· AI review 20% (missing components rescaled out). Rolls up lesson→chapter→grade.
Errors are tracked separately and do NOT affect health.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

st.set_page_config(
    page_title="Cuemath · Curriculum Efficacy",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

from processing.health import compute_health
from processing.pipeline import run_pipeline
from utils.cache import all_results as load_all_results, save_all_results
from dashboard import simple_view


# ── Core pipeline (thin Streamlit wrapper over processing.pipeline) ───────────
def process_all_lessons(force: bool = False) -> dict:
    bar = st.progress(0, text="Fetching lesson reviews…")

    def _prog(pct, text=""):
        try:
            bar.progress(min(int(pct), 100), text=text)
        except Exception:  # noqa: BLE001
            pass

    try:
        return run_pipeline(force=force, progress=_prog, warn=st.warning)
    finally:
        try:
            bar.empty()
        except Exception:  # noqa: BLE001
            pass


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
    if "ai_reviews" not in st.session_state:
        # Preload any AI reviews already generated (e.g. by the bulk run) so the
        # detail view shows them without re-calling the LLM.
        from processing.ai_expert_review import get_cached_ai_reviews
        try:
            st.session_state["ai_reviews"] = get_cached_ai_reviews()
        except Exception:  # noqa: BLE001
            st.session_state["ai_reviews"] = {}
    st.session_state.setdefault("nav", {})
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
            simple_view.render_grade_nav(results, nav, mode)

        st.divider()
        complete = [r for r in results.values() if r.get("status") == "Complete"]
        st.caption(f"{len(complete)} complete · {len(results) - len(complete)} pending")

        st.caption("✨ AI review is being piloted on one lesson "
                   "(G4 · Determine Median and Range). Rollout to all lessons is "
                   "pending approval.")

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
