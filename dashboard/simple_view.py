"""Simple UI — Grade → Chapter → Lesson drill-down with 4-component health.

Deliberately plain (Streamlit-native widgets, minimal HTML). The old rich
master/detail views are kept in the repo but no longer wired into app.py.
"""
from __future__ import annotations

import streamlit as st

from processing.health import rollup, HEALTH_LABELS, HEALTH_WEIGHTS

_RAG_EMOJI = {"Good": "🟢", "Average": "🟡", "Bad": "🔴", "Pending": "⚪"}
_CHECK_LABELS = {
    "flow": "Flow", "visuals": "Visuals & simulations", "text_load": "Text load",
    "response_boxes": "Response boxes", "accuracy": "Accuracy",
}


def _rag(rating: str) -> str:
    return f"{_RAG_EMOJI.get(rating, '⚪')} {rating}"


def _lesson_score(r: dict) -> float:
    return float(r.get("weighted_score") or 0) if r.get("status") == "Complete" else 0.0


# ── Rollups ────────────────────────────────────────────────────────────────────

def _group_tree(results: dict) -> dict:
    """{grade: {chapter: [result, ...]}} in a stable order."""
    tree: dict = {}
    for r in results.values():
        g = r.get("grade") or "Unknown grade"
        c = r.get("chapter") or "Unknown chapter"
        tree.setdefault(g, {}).setdefault(c, []).append(r)
    return tree


def _grade_sort_key(g: str):
    import re
    m = re.search(r"\d+", g or "")
    return (0, int(m.group())) if m else (1, g)


# ── Views ────────────────────────────────────────────────────────────────────

def render_home(results: dict, nav) -> None:
    st.subheader("Curriculum health by grade")
    st.caption(
        "Health = Teacher Sheet 40% · Class review 30% · Exit-ticket data 10% · "
        "AI review 20% (missing components are rescaled out). "
        "Bands: Good ≥4.0 · Average 2.5–3.9 · Bad <2.5."
    )

    tree = _group_tree(results)
    if not tree:
        st.info("No data yet — click **Refresh Data** in the sidebar.")
        return

    for grade in sorted(tree, key=_grade_sort_key):
        chapters = tree[grade]
        lesson_scores = [
            _lesson_score(r) for ch in chapters.values() for r in ch
            if r.get("status") == "Complete"
        ]
        roll = rollup(lesson_scores)
        n_lessons = sum(len(ch) for ch in chapters.values())
        n_complete = sum(1 for ch in chapters.values() for r in ch if r.get("status") == "Complete")

        c1, c2, c3 = st.columns([4, 2, 2])
        with c1:
            st.markdown(f"### {grade}")
            st.caption(f"{len(chapters)} chapters · {n_complete}/{n_lessons} lessons complete")
        with c2:
            st.metric("Health", f"{roll['score']:.1f}" if roll["n"] else "—",
                      _rag(roll["rating"]), label_visibility="visible")
        with c3:
            if st.button("Open →", key=f"grade_{grade}", use_container_width=True):
                nav(grade=grade)
        st.divider()


def render_grade(results: dict, grade: str, nav) -> None:
    if st.button("← All grades"):
        nav(home=True)
    st.subheader(f"{grade} · chapters")

    tree = _group_tree(results).get(grade, {})
    for chapter in sorted(tree):
        lessons = tree[chapter]
        scores = [_lesson_score(r) for r in lessons if r.get("status") == "Complete"]
        roll = rollup(scores)
        n_complete = sum(1 for r in lessons if r.get("status") == "Complete")

        c1, c2, c3 = st.columns([4, 2, 2])
        with c1:
            st.markdown(f"**{chapter}**")
            st.caption(f"{n_complete}/{len(lessons)} lessons complete")
        with c2:
            st.metric("Health", f"{roll['score']:.1f}" if roll["n"] else "—", _rag(roll["rating"]))
        with c3:
            if st.button("Open →", key=f"chap_{grade}_{chapter}", use_container_width=True):
                nav(grade=grade, chapter=chapter)
        st.divider()


def render_chapter(results: dict, grade: str, chapter: str, nav) -> None:
    if st.button("← Chapters"):
        nav(grade=grade)
    st.subheader(f"{chapter} · lessons")

    lessons = _group_tree(results).get(grade, {}).get(chapter, [])
    for r in sorted(lessons, key=lambda x: x.get("lesson", "")):
        ref = r.get("activity_ref", "")
        complete = r.get("status") == "Complete"
        score = _lesson_score(r)
        rating = r.get("final_rating", "Pending")

        c1, c2, c3 = st.columns([5, 2, 2])
        with c1:
            st.markdown(f"**{r.get('lesson') or ref}**")
            st.caption(r.get("one_line_summary", "") if complete
                       else r.get("one_line_summary", "Pending review."))
        with c2:
            st.metric("Health", f"{score:.1f}" if complete else "—", _rag(rating))
        with c3:
            if st.button("View →", key=f"lesson_{ref}", use_container_width=True):
                nav(grade=grade, chapter=chapter, lesson=ref)
        st.divider()


def render_lesson(result: dict, nav, on_generate_ai) -> None:
    grade = result.get("grade", "")
    chapter = result.get("chapter", "")
    if st.button("← Lessons"):
        nav(grade=grade, chapter=chapter)

    st.subheader(result.get("lesson") or result.get("activity_ref", ""))
    st.caption(f"{grade} · {chapter} · `{result.get('activity_ref','')}`")

    if result.get("status") != "Complete":
        st.warning(result.get("one_line_summary", "This lesson is still pending review."))
        _render_errors(result)
        return

    health = result.get("health", {})
    score = float(result.get("weighted_score") or 0)
    rating = result.get("final_rating", "Pending")

    # ── Headline health ──────────────────────────────────────────────────────
    st.markdown(f"## {_rag(rating)}  ·  {score:.1f}/5")
    st.caption(result.get("final_rationale", ""))

    # ── 4-component breakdown ─────────────────────────────────────────────────
    st.markdown("#### Health components")
    comps = health.get("components", {})
    weights = health.get("weights", {})
    cols = st.columns(4)
    for i, key in enumerate(["teacher", "classroom", "exit_data", "ai"]):
        with cols[i]:
            if key in comps:
                st.metric(
                    HEALTH_LABELS[key],
                    f"{comps[key]:.1f}/5",
                    f"{weights[key]}% (of {HEALTH_WEIGHTS[key]}% nominal)",
                    delta_color="off",
                )
            else:
                st.metric(HEALTH_LABELS[key], "—",
                          f"{HEALTH_WEIGHTS[key]}% — not available", delta_color="off")

    # ── Teacher-sheet sections ────────────────────────────────────────────────
    st.markdown("#### Teacher Sheet sections")
    parts = result.get("teacher_parts", {})
    sc = st.columns(4)
    for i, (key, label) in enumerate([("learning", "Learning"), ("practice", "Practice"),
                                      ("mini_quiz", "Mini-Quiz"), ("overall", "Overall")]):
        with sc[i]:
            v = parts.get(key, 0)
            st.metric(label, f"{v:.1f}/5" if v else "—")

    # ── Learning items ────────────────────────────────────────────────────────
    fa = [r for r in result.get("flow_a_results", []) if r.get("rating") != "Pending"]
    if fa:
        with st.expander(f"Learning items ({len(fa)})", expanded=False):
            for item in fa:
                st.markdown(f"**{item.get('item_ref','')}** — {_rag(item.get('rating',''))} "
                            f"{float(item.get('score') or 0):.1f}/5 "
                            f"· {item.get('teacher_count',0)} teacher(s)")
                st.caption(item.get("rationale", ""))

    # ── AI review (the 20% component) ─────────────────────────────────────────
    st.markdown("#### AI review of learning items")
    _render_ai_review(result, on_generate_ai)

    # ── Errors ────────────────────────────────────────────────────────────────
    _render_errors(result)


def _render_ai_review(result: dict, on_generate_ai) -> None:
    ref = result.get("activity_ref", "")
    ai = st.session_state.get("ai_reviews", {}).get(ref)

    if ai is None:
        st.caption("The AI review scores the learning items (Flow, Visuals & simulations, "
                   "Text load, Response boxes, Accuracy) and contributes 20% of health.")
        if st.button("✨ Generate AI review", key=f"gen_ai_{ref}"):
            with st.spinner("Generating AI review…"):
                ai = on_generate_ai(ref)
            st.rerun()
        return

    if ai.get("error"):
        st.error(f"AI review failed: {ai['error']}")
        if st.button("Retry", key=f"retry_ai_{ref}"):
            st.session_state.get("ai_reviews", {}).pop(ref, None)
            st.rerun()
        return

    ai_score = ai.get("ai_score")
    if ai_score is not None:
        st.markdown(f"**AI score: {float(ai_score):.1f}/5** · {ai.get('final_rating','')}")
    if ai.get("confidence_note"):
        st.caption(ai["confidence_note"])
    if ai.get("overall_summary"):
        st.write(ai["overall_summary"])

    checks = ai.get("checks") or {}
    for key, label in _CHECK_LABELS.items():
        c = checks.get(key)
        if not isinstance(c, dict):
            continue
        status = c.get("status", "")
        icon = "✅" if "well" in status.lower() else "🔧"
        st.markdown(f"{icon} **{label}** — {status}")
        if c.get("comment"):
            st.caption(c["comment"])

    if ai.get("concerns"):
        st.markdown("**Needs curriculum intervention:**")
        for x in ai["concerns"]:
            st.markdown(f"- {x}")

    if st.button("↻ Regenerate", key=f"regen_ai_{ref}"):
        st.session_state.get("ai_reviews", {}).pop(ref, None)
        st.rerun()


def _render_errors(result: dict) -> None:
    errors = result.get("detected_errors") or result.get("error_reports") or []
    st.markdown(f"#### 🚩 Errors reported ({len(errors)})")
    st.caption("Errors are tracked here only — they do **not** affect the health score.")
    if not errors:
        st.caption("No errors reported for this lesson.")
        return
    for e in errors:
        item = e.get("item_ref") or e.get("item") or ""
        sev = e.get("severity", "")
        text = e.get("text") or e.get("error_details") or e.get("error_type") or ""
        who = e.get("reviewer") or e.get("reviewer_name") or ""
        head = f"**{item}**" if item else "**(lesson)**"
        st.markdown(f"{head} {f'· _{sev}_' if sev else ''} — {text}"
                    + (f"  \n<sub>— {who}</sub>" if who else ""), unsafe_allow_html=True)
