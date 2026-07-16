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

def _comp_header(key: str, emoji: str, health: dict) -> str:
    """Expander title for a health component — shows its score + weight, or 'n/a'."""
    comps = health.get("components", {})
    weights = health.get("weights", {})
    name = HEALTH_LABELS[key]
    if key in comps:
        return f"{emoji}  {name}  —  {comps[key]:.1f}/5   ·   {weights[key]}% of health"
    return f"{emoji}  {name}  —  not available   ·   {HEALTH_WEIGHTS[key]}% redistributed"


def _render_lesson_body(result: dict, on_generate_ai) -> None:
    st.markdown(f"### {result.get('lesson') or result.get('activity_ref','')}")
    st.caption(f"`{result.get('activity_ref','')}`")

    if result.get("status") != "Complete":
        st.warning(result.get("one_line_summary", "This lesson is still pending review."))
        return

    score = float(result.get("weighted_score") or 0)
    rating = result.get("final_rating", "Pending")
    health = result.get("health", {})

    # ── Headline health only; the four components are collapsed below ─────────
    st.markdown(f"## Health: {_rag(rating)}  ·  {score:.1f}/5")
    st.caption("Weighted from the components below (missing ones are redistributed). "
               "Click a component to see how it's rated.")

    # 1 ── Teacher Sheet review (covers Learning / Practice / Mini-Quiz / Overall)
    with st.expander(_comp_header("teacher", "🧑‍🏫", health), expanded=False):
        parts = result.get("teacher_parts", {})
        cols = st.columns(4)
        for i, (k, label) in enumerate([("learning", "Learning"), ("practice", "Practice"),
                                        ("mini_quiz", "Mini-Quiz"), ("overall", "Overall")]):
            with cols[i]:
                v = parts.get(k, 0)
                st.metric(label, f"{v:.1f}/5" if v else "—")
        fa = [r for r in result.get("flow_a_results", []) if r.get("rating") != "Pending"]
        if fa:
            st.caption("Teacher item-level ratings:")
            for item in fa:
                st.markdown(f"- **{item.get('item_ref','')}** — {_rag(item.get('rating',''))} "
                            f"{float(item.get('score') or 0):.1f}/5 "
                            f"· {item.get('teacher_count',0)} teacher(s)")

        # ── Teacher divergence — where reviewers disagree (spread > 1.5) ──────
        divs = [(item.get("item_ref", ""), d)
                for item in fa for d in (item.get("divergences") or [])]
        st.markdown("**⚠️ Teacher divergence**")
        if divs:
            st.caption("Learning items where reviewers differ by more than 1.5 points — "
                       "worth a closer look:")
            for item_ref, d in divs:
                st.markdown(
                    f"- **{item_ref}** · _{d.get('dimension','')}_ — "
                    f"spread {d.get('spread','?')} pts  ·  {d.get('teacher_positions','')}")
        else:
            st.caption("No notable divergence — reviewers broadly agree on every item.")

    # 2 ── Class review
    with st.expander(_comp_header("classroom", "👥", health), expanded=False):
        cr = result.get("section_ratings", {}).get("classroom_review", {})
        if cr.get("score"):
            st.write(cr.get("rationale", ""))
        else:
            st.caption("No classroom review matched this lesson yet.")

    # 3 ── Exit-ticket data
    with st.expander(_comp_header("exit_data", "📝", health), expanded=False):
        ed = result.get("exit_data")
        if ed:
            st.markdown(f"**{ed.get('pct', 0):.0f}%** exit-ticket performance  →  "
                        f"**{ed.get('score_5', 0):.1f}/5**")
            st.caption(f"Mean of (avg-score ÷ max-score) × 100 across "
                       f"{ed.get('n_items', 0)} exit item(s) / {ed.get('n_widgets', 0)} widget(s), "
                       "then scaled linearly to 1–5 (100% = 5.0).")
        else:
            st.info("No exit-ticket data matched this lesson.")

    # 4 ── AI review of learning items
    with st.expander(_comp_header("ai", "✨", health), expanded=False):
        _render_ai_review(result, on_generate_ai)


def _render_ai_review(result: dict, on_generate_ai) -> None:
    ref = result.get("activity_ref", "")
    ai = st.session_state.get("ai_reviews", {}).get(ref)

    if ai is None:
        st.caption("AI review is being piloted on selected lessons — not enabled here yet.")
        return
    if ai.get("error"):
        st.caption("AI review unavailable for this lesson (no item content).")
        return

    ai_score = ai.get("ai_score")
    if ai_score is not None:
        st.markdown(f"**AI score: {float(ai_score):.1f}/5** · {ai.get('final_rating','')} "
                    "— reviewed per learning item against the gold-standard framework")
    if ai.get("confidence_note"):
        st.caption(ai["confidence_note"])

    items = ai.get("items") or []
    if items:
        for it in items:
            if not isinstance(it, dict):
                continue
            sc = it.get("score")
            sc_txt = f"{float(sc):.1f}/5" if isinstance(sc, (int, float)) else "—"
            emoji = _RAG_EMOJI.get(_rating_from(sc), "⚪")
            st.markdown(f"**{emoji} {it.get('reference','item')} — {sc_txt}**")
            checks = it.get("checks") or {}
            chips = [f"{lbl} {'✅' if str(checks.get(k,'')).lower().startswith('ok') else '🔧'}"
                     for k, lbl in [("flow", "Flow"), ("visuals", "Visuals"),
                                    ("text_load", "Text"), ("response_boxes", "Boxes"),
                                    ("accuracy", "Accuracy")] if k in checks]
            if chips:
                st.caption("  ·  ".join(chips))
            if it.get("verdict"):
                st.write(it["verdict"])
            for fx in (it.get("fixes") or []):
                st.markdown(f"- {fx}")
            st.divider()
    else:
        # Fallback for the older combined format.
        if ai.get("overall_summary"):
            st.write(ai["overall_summary"])
        for x in (ai.get("concerns") or []):
            st.markdown(f"- {x}")


def _rating_from(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "N/A"
    return "Good" if s >= 4.0 else "Average" if s >= 2.5 else "Bad"


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
