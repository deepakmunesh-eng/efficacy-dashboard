"""Simple two-pane UI — persistent Grade nav (left) + content (right).

Left pane: the grade list (always visible, selected grade highlighted).
Right pane: chapters -> lessons -> lesson detail for the selected grade.
A top toggle switches between Health and Errors-reported modes; both drill down
the same Grade -> Chapter -> Lesson tree (errors are NOT a flat spreadsheet).
"""
from __future__ import annotations

import re

import streamlit as st

from processing.health import rollup, HEALTH_LABELS, HEALTH_WEIGHTS

_RAG_EMOJI = {"Good": "🟢", "Average": "🟡", "Bad": "🔴", "Pending": "⚪", "N/A": "⚪"}
_CHECK_LABELS = {
    "flow": "Flow", "visuals": "Visuals & simulations", "text_load": "Text load",
    "response_boxes": "Response boxes", "accuracy": "Accuracy",
}


def _rag(rating: str) -> str:
    return f"{_RAG_EMOJI.get(rating, '⚪')} {rating}"


def _lesson_score(r: dict) -> float:
    return float(r.get("weighted_score") or 0) if r.get("status") == "Complete" else 0.0


def _err_count(r: dict) -> int:
    return len(r.get("detected_errors") or r.get("error_reports") or [])


def _grade_label(g: str) -> str:
    g = str(g).strip()
    if g.upper() in ("KG", "K"):
        return "Grade K"
    if g.isdigit():
        return f"Grade {g}"
    return g if g.lower().startswith("grade") else f"Grade {g}"


def _grade_sort_key(g: str):
    if str(g).upper() in ("KG", "K"):
        return (0, -1)
    m = re.search(r"\d+", str(g) or "")
    return (0, int(m.group())) if m else (1, str(g))


def _group_tree(results: dict) -> dict:
    """{grade: {chapter: [result, ...]}}."""
    tree: dict = {}
    for r in results.values():
        g = r.get("grade") or "Unknown"
        c = r.get("chapter") or "Unknown chapter"
        tree.setdefault(g, {}).setdefault(c, []).append(r)
    return tree


# ── Chips ──────────────────────────────────────────────────────────────────────

def _health_chip(scores: list[float]) -> str:
    roll = rollup(scores)
    if not roll["n"]:
        return "⚪ —"
    return f"{_RAG_EMOJI.get(roll['rating'], '⚪')} {roll['score']:.1f}"


def _errors_chip(count: int) -> str:
    return f"🚩 {count}" if count else "· 0"


# ── Two-pane browse ─────────────────────────────────────────────────────────────

def render_browse(results: dict, nav, on_generate_ai, mode: str) -> None:
    tree = _group_tree(results)
    grades = sorted(tree, key=_grade_sort_key)
    if not grades:
        st.info("No data yet — click **Refresh Data** in the sidebar.")
        return

    n = st.session_state["nav"]
    sel_grade = n.get("grade") if n.get("grade") in tree else grades[0]

    left, right = st.columns([1, 3.4], gap="medium")

    # ── Left: grade list (persistent) ─────────────────────────────────────────
    with left:
        st.markdown("###### 📁 USCC")
        for g in grades:
            selected = (g == sel_grade)
            if st.button(_grade_label(g), key=f"gnav_{mode}_{g}",
                         use_container_width=True,
                         type="primary" if selected else "secondary"):
                nav(grade=g, mode=mode)

    # ── Right: chapters / lessons / detail ────────────────────────────────────
    with right:
        if n.get("lesson"):
            r = results.get(n["lesson"])
            if not r:
                st.error("Lesson not found."); return
            _breadcrumb(nav, mode, sel_grade, r.get("chapter"), r.get("lesson"))
            if mode == "errors":
                _render_errors(r, heading=True)
            else:
                _render_lesson_body(r, on_generate_ai)
        elif n.get("chapter"):
            _render_lesson_list(tree, sel_grade, n["chapter"], nav, mode)
        else:
            _render_chapter_list(tree, sel_grade, nav, mode)


def _breadcrumb(nav, mode, grade, chapter, lesson=None) -> None:
    c1, c2 = st.columns([3, 1])
    with c1:
        trail = f"{_grade_label(grade)}  ›  {chapter}"
        if lesson:
            trail += f"  ›  **{lesson}**"
        st.markdown(trail)
    with c2:
        back_to = "chapters" if lesson else "grades"
        if st.button(f"← {'Lessons' if lesson else 'Chapters'}", use_container_width=True):
            if lesson:
                nav(grade=grade, chapter=chapter, mode=mode)
            else:
                nav(grade=grade, mode=mode)


def _render_chapter_list(tree, grade, nav, mode) -> None:
    st.markdown(f"### {_grade_label(grade)}")
    chapters = tree.get(grade, {})
    for chapter in sorted(chapters):
        lessons = chapters[chapter]
        if mode == "errors":
            chip = _errors_chip(sum(_err_count(r) for r in lessons))
        else:
            chip = _health_chip([_lesson_score(r) for r in lessons
                                 if r.get("status") == "Complete"])
        n_complete = sum(1 for r in lessons if r.get("status") == "Complete")
        if st.button(f"{chip}   ·   {chapter}   ({n_complete}/{len(lessons)})",
                     key=f"ch_{mode}_{grade}_{chapter}", use_container_width=True):
            nav(grade=grade, chapter=chapter, mode=mode)


def _render_lesson_list(tree, grade, chapter, nav, mode) -> None:
    _breadcrumb(nav, mode, grade, chapter)
    st.markdown(f"### {chapter}")
    for r in sorted(tree.get(grade, {}).get(chapter, []), key=lambda x: x.get("lesson", "")):
        ref = r.get("activity_ref", "")
        complete = r.get("status") == "Complete"
        if mode == "errors":
            chip = _errors_chip(_err_count(r))
        else:
            chip = (f"{_RAG_EMOJI.get(r.get('final_rating'), '⚪')} "
                    f"{_lesson_score(r):.1f}" if complete else "⚪ —")
        name = r.get("lesson") or ref
        if st.button(f"{chip}   ·   {name}", key=f"ls_{mode}_{ref}",
                     use_container_width=True):
            nav(grade=grade, chapter=chapter, lesson=ref, mode=mode)


# ── Lesson detail ────────────────────────────────────────────────────────────

def _render_lesson_body(result: dict, on_generate_ai) -> None:
    st.markdown(f"### {result.get('lesson') or result.get('activity_ref','')}")
    st.caption(f"`{result.get('activity_ref','')}`")

    if result.get("status") != "Complete":
        st.warning(result.get("one_line_summary", "This lesson is still pending review."))
        _render_errors(result)
        return

    score = float(result.get("weighted_score") or 0)
    rating = result.get("final_rating", "Pending")
    st.markdown(f"## {_rag(rating)}  ·  {score:.1f}/5")
    st.caption(result.get("final_rationale", ""))

    health = result.get("health", {})
    comps = health.get("components", {})
    weights = health.get("weights", {})
    st.markdown("#### Health components")
    cols = st.columns(4)
    for i, key in enumerate(["teacher", "classroom", "exit_data", "ai"]):
        with cols[i]:
            if key in comps:
                st.metric(HEALTH_LABELS[key], f"{comps[key]:.1f}/5",
                          f"{weights[key]}% wt", delta_color="off")
            else:
                st.metric(HEALTH_LABELS[key], "—",
                          f"{HEALTH_WEIGHTS[key]}% n/a", delta_color="off")

    st.markdown("#### Teacher Sheet sections")
    parts = result.get("teacher_parts", {})
    sc = st.columns(4)
    for i, (key, label) in enumerate([("learning", "Learning"), ("practice", "Practice"),
                                      ("mini_quiz", "Mini-Quiz"), ("overall", "Overall")]):
        with sc[i]:
            v = parts.get(key, 0)
            st.metric(label, f"{v:.1f}/5" if v else "—")

    fa = [r for r in result.get("flow_a_results", []) if r.get("rating") != "Pending"]
    if fa:
        with st.expander(f"Learning items ({len(fa)})", expanded=False):
            for item in fa:
                st.markdown(f"**{item.get('item_ref','')}** — {_rag(item.get('rating',''))} "
                            f"{float(item.get('score') or 0):.1f}/5 · {item.get('teacher_count',0)} teacher(s)")
                st.caption(item.get("rationale", ""))

    st.markdown("#### AI review of learning items")
    _render_ai_review(result, on_generate_ai)

    with st.expander(f"🚩 Errors reported ({_err_count(result)})", expanded=False):
        _render_errors(result, heading=False)


def _render_ai_review(result: dict, on_generate_ai) -> None:
    from config.settings import AI_REVIEW_ENABLED

    ref = result.get("activity_ref", "")
    ai = st.session_state.get("ai_reviews", {}).get(ref)

    if not AI_REVIEW_ENABLED and ai is None:
        st.info(
            "🔒 **AI review — awaiting Learnosity access.**  Once enabled, it scores the "
            "learning items against the gold-standard reference across the five checks "
            "(Flow, Visuals & simulations, Text load, Response boxes, Accuracy) and "
            "contributes **20%** of health. Until then its weight is redistributed."
        )
        return

    if ai is None:
        st.caption("Scores learning items (Flow, Visuals, Text load, Response boxes, "
                   "Accuracy); contributes 20% of health.")
        if st.button("✨ Generate AI review", key=f"gen_ai_{ref}"):
            with st.spinner("Generating AI review…"):
                on_generate_ai(ref)
            st.rerun()
        return

    if ai.get("error"):
        st.error(f"AI review failed: {ai['error']}")
        if st.button("Retry", key=f"retry_ai_{ref}"):
            st.session_state.get("ai_reviews", {}).pop(ref, None); st.rerun()
        return

    ai_score = ai.get("ai_score")
    if ai_score is not None:
        st.markdown(f"**AI score: {float(ai_score):.1f}/5** · {ai.get('final_rating','')}")
    if ai.get("confidence_note"):
        st.caption(ai["confidence_note"])
    if ai.get("overall_summary"):
        st.write(ai["overall_summary"])
    for key, label in _CHECK_LABELS.items():
        c = (ai.get("checks") or {}).get(key)
        if not isinstance(c, dict):
            continue
        icon = "✅" if "well" in c.get("status", "").lower() else "🔧"
        st.markdown(f"{icon} **{label}** — {c.get('status','')}")
        if c.get("comment"):
            st.caption(c["comment"])
    if ai.get("concerns"):
        st.markdown("**Needs curriculum intervention:**")
        for x in ai["concerns"]:
            st.markdown(f"- {x}")
    if st.button("↻ Regenerate", key=f"regen_ai_{ref}"):
        st.session_state.get("ai_reviews", {}).pop(ref, None); st.rerun()


def _render_errors(result: dict, heading: bool = True) -> None:
    errors = result.get("detected_errors") or result.get("error_reports") or []
    if heading:
        st.markdown(f"### {result.get('lesson') or result.get('activity_ref','')}")
        st.caption(f"`{result.get('activity_ref','')}` · errors do not affect health")
    if not errors:
        st.success("No errors reported for this lesson. 🎉")
        return
    for e in errors:
        item = e.get("item_ref") or e.get("item") or ""
        sev = (e.get("severity") or "").strip()
        text = e.get("text") or e.get("error_details") or e.get("error_type") or ""
        who = e.get("reviewer") or e.get("reviewer_name") or ""
        sev_icon = {"severe": "🔴", "moderate": "🟠", "minor": "🟡"}.get(sev.lower(), "🚩")
        head = f"**{item}**" if item else "**(lesson-level)**"
        st.markdown(f"{sev_icon} {head}" + (f" · _{sev}_" if sev else "") + f" — {text}")
        if who:
            st.caption(f"— {who}")
