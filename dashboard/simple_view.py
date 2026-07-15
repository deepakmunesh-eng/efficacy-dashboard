"""Simple UI — grade nav lives in the SIDEBAR; the main area is full-width.

Sidebar: Refresh, a view selector (Health / Errors reported), then the grade
list. Main area: chapters -> lessons -> lesson detail for the selected grade,
using the full width (no cramped side column). Health and Errors are separate
views chosen in the sidebar; both drill the same Grade -> Chapter -> Lesson tree.
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
    tree: dict = {}
    for r in results.values():
        g = r.get("grade") or "Unknown"
        c = r.get("chapter") or "Unknown chapter"
        tree.setdefault(g, {}).setdefault(c, []).append(r)
    return tree


def _selected_grade(tree: dict, grades: list) -> str | None:
    n = st.session_state.get("nav", {})
    if n.get("grade") in tree:
        return n["grade"]
    return grades[0] if grades else None


# ── Chips ──────────────────────────────────────────────────────────────────────

def _health_chip(scores: list[float]) -> str:
    roll = rollup(scores)
    if not roll["n"]:
        return "⚪ —"
    return f"{_RAG_EMOJI.get(roll['rating'], '⚪')} {roll['score']:.1f}"


def _errors_chip(count: int) -> str:
    return f"🚩 {count}" if count else "·"


# ── Sidebar grade nav ───────────────────────────────────────────────────────────

def _grade_chip(chapters: dict, mode: str) -> str:
    lessons = [r for ch in chapters.values() for r in ch]
    if mode == "errors":
        return _errors_chip(sum(_err_count(r) for r in lessons))
    return _health_chip([_lesson_score(r) for r in lessons if r.get("status") == "Complete"])


def render_grade_nav(results: dict, nav, mode: str = "health") -> None:
    """Render the grade list with a grade-level rating/error chip.
    Call this inside a `with st.sidebar:` block."""
    tree = _group_tree(results)
    grades = sorted(tree, key=_grade_sort_key)
    if not grades:
        st.caption("No grades yet — Refresh.")
        return
    sel = _selected_grade(tree, grades)
    st.markdown("###### 📁 USCC")
    for g in grades:
        selected = (g == sel)
        chip = _grade_chip(tree[g], mode)
        if st.button(f"{_grade_label(g)}   ·   {chip}", key=f"gnav_{g}",
                     use_container_width=True,
                     type="primary" if selected else "secondary"):
            nav(grade=g)


# ── Main content (full width) ────────────────────────────────────────────────

def render_content(results: dict, nav, on_generate_ai, mode: str) -> None:
    tree = _group_tree(results)
    grades = sorted(tree, key=_grade_sort_key)
    if not grades:
        st.info("No data yet — click **Refresh Data** in the sidebar.")
        return
    sel = _selected_grade(tree, grades)
    n = st.session_state["nav"]

    if n.get("lesson"):
        r = results.get(n["lesson"])
        if not r:
            st.error("Lesson not found."); return
        _breadcrumb(nav, sel, r.get("chapter"), r.get("lesson"))
        if mode == "errors":
            _render_errors(r, heading=True)
        else:
            _render_lesson_body(r, on_generate_ai)
    elif n.get("chapter"):
        _render_lesson_list(tree, sel, n["chapter"], nav, mode)
    else:
        _render_chapter_list(tree, sel, nav, mode)


def _breadcrumb(nav, grade, chapter, lesson=None) -> None:
    c1, c2 = st.columns([4, 1])
    with c1:
        trail = f"{_grade_label(grade)}  ›  {chapter}"
        if lesson:
            trail += f"  ›  **{lesson}**"
        st.markdown(trail)
    with c2:
        if st.button(f"← {'Lessons' if lesson else 'Chapters'}", use_container_width=True):
            nav(grade=grade, chapter=chapter) if lesson else nav(grade=grade)


def _render_chapter_list(tree, grade, nav, mode) -> None:
    chapters = tree.get(grade, {})
    all_lessons = [r for ls in chapters.values() for r in ls]

    # ── Grade-level rating banner ─────────────────────────────────────────────
    if mode == "errors":
        total_err = sum(_err_count(r) for r in all_lessons)
        st.markdown(f"### {_grade_label(grade)} · 🚩 {total_err} error(s)")
    else:
        roll = rollup([_lesson_score(r) for r in all_lessons if r.get("status") == "Complete"])
        chip = (f"{_RAG_EMOJI.get(roll['rating'], '⚪')} {roll['score']:.1f}/5 · {roll['rating']}"
                if roll["n"] else "⚪ Pending")
        st.markdown(f"### {_grade_label(grade)} · {chip}")
    n_comp = sum(1 for r in all_lessons if r.get("status") == "Complete")
    st.caption(f"{len(chapters)} chapters · {n_comp}/{len(all_lessons)} lessons complete "
               "· click a chapter to open its lessons")

    # ── Chapter grid (3 per row → fits one screen, no long scroll) ────────────
    names = sorted(chapters)
    n_cols = 3
    for row_start in range(0, len(names), n_cols):
        cols = st.columns(n_cols)
        for col, chapter in zip(cols, names[row_start:row_start + n_cols]):
            lessons = chapters[chapter]
            if mode == "errors":
                chip = _errors_chip(sum(_err_count(r) for r in lessons))
            else:
                chip = _health_chip([_lesson_score(r) for r in lessons
                                     if r.get("status") == "Complete"])
            with col:
                if st.button(f"{chip}\n\n{chapter}",
                             key=f"ch_{mode}_{grade}_{chapter}", use_container_width=True):
                    nav(grade=grade, chapter=chapter)


def _render_lesson_list(tree, grade, chapter, nav, mode) -> None:
    _breadcrumb(nav, grade, chapter)
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
            nav(grade=grade, chapter=chapter, lesson=ref)


# ── Lesson detail ────────────────────────────────────────────────────────────

def _render_lesson_body(result: dict, on_generate_ai) -> None:
    st.markdown(f"### {result.get('lesson') or result.get('activity_ref','')}")
    st.caption(f"`{result.get('activity_ref','')}`")

    if result.get("status") != "Complete":
        st.warning(result.get("one_line_summary", "This lesson is still pending review."))
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
        st.caption("Scores learning items across the five checks; contributes 20% of health.")
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
