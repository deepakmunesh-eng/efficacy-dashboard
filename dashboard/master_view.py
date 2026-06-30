"""Master dashboard — hierarchical Program → Grade → Chapter → Lesson navigation."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.helpers import truncate, safe_float

_NAVY   = "#0E1B3D"
_GREEN  = "#2DBD6E"
_AMBER  = "#F59E0B"
_RED    = "#E84C3D"
_MUTED  = "#5B6B82"
_BORDER = "#E4EAF3"

_RAG_COLOR = {"Good": _GREEN, "Average": _AMBER, "Bad": _RED, "Pending": "#94A3B8"}
_RAG_BG    = {"Good": "#EDFAF3", "Average": "#FFF8EB", "Bad": "#FEF1F1", "Pending": "#F8FAFC"}
_RAG_TEXT  = {"Good": "#156D3E", "Average": "#8A5800", "Bad": "#9B1C1C", "Pending": "#475569"}
_RAG_DOT   = {"Good": "🟢", "Average": "🟡", "Bad": "🔴", "Pending": "⏳"}


# ── Data builder ───────────────────────────────────────────────────────────────

def _build_df(all_results: dict) -> pd.DataFrame:
    rows = []
    for ref, res in all_results.items():
        sr     = res.get("section_ratings") or {}
        tnames = res.get("teacher_names") or []
        rows.append({
            "activity_ref": ref,
            "Grade":       (res.get("grade")   or "").strip(),
            "Chapter":     (res.get("chapter") or "").strip(),
            "Lesson":      (res.get("lesson")  or "").strip(),
            "Status":      res.get("status", "Pending"),
            "RAG":         res.get("final_rating", "Pending"),
            "Avg Rating":  res.get("avg_teacher_rating") or 0.0,
            "Learning":    (sr.get("learning")    or {}).get("rating", "—"),
            "Practice":    (sr.get("practice")    or {}).get("rating", "—"),
            "Exit Ticket": (sr.get("exit_ticket") or {}).get("rating", "—"),
            "Teachers":    ", ".join(tnames),
            "Review Date": res.get("review_date", ""),
            "Summary":     truncate(res.get("one_line_summary", ""), 120),
            "Reviewers":   len(tnames),
        })
    return pd.DataFrame(rows)


def _mini_bar(good: int, avg: int, bad: int, pend: int) -> str:
    total = good + avg + bad + pend or 1
    segs  = [(good, _GREEN), (avg, _AMBER), (bad, _RED), (pend, "#94A3B8")]
    bars  = "".join(
        f'<div style="flex:{n};background:{c};height:7px;border-radius:4px;'
        f'min-width:{max(3, int(n / total * 64))}px"></div>'
        for n, c in segs if n > 0
    )
    return f'<div style="display:flex;gap:2px;align-items:center;width:100%">{bars}</div>'


def _stat_pill(count: int, color: str, dot: str) -> str:
    return (
        f'<span style="background:{color}1A;color:{color};'
        f'padding:2px 8px;border-radius:12px;font-size:0.7rem;font-weight:700;">'
        f'{dot}{count}</span>'
    )


# ── Navigation helpers ─────────────────────────────────────────────────────────

def _nav_back_to(level: str) -> None:
    if level == "program":
        for k in ("nav_program", "nav_grade", "nav_chapter", "selected_lesson"):
            st.session_state.pop(k, None)
    elif level == "grade":
        for k in ("nav_grade", "nav_chapter", "selected_lesson"):
            st.session_state.pop(k, None)
    elif level == "chapter":
        for k in ("nav_chapter", "selected_lesson"):
            st.session_state.pop(k, None)
    st.rerun()


def _render_breadcrumb() -> None:
    nav_program = st.session_state.get("nav_program")
    nav_grade   = st.session_state.get("nav_grade")
    nav_chapter = st.session_state.get("nav_chapter")

    crumbs: list[tuple[str, str | None]] = [("Programs", "program")]
    if nav_program:
        crumbs.append((nav_program, "grade" if (nav_grade or nav_chapter) else None))
    if nav_grade:
        lbl = f"Grade {nav_grade}" if str(nav_grade).upper() != "K" else "Grade K"
        crumbs.append((lbl, "chapter" if nav_chapter else None))
    if nav_chapter:
        crumbs.append((nav_chapter, None))

    parts_html = []
    for i, (label, back_level) in enumerate(crumbs):
        is_last = i == len(crumbs) - 1
        if is_last:
            parts_html.append(
                f'<span style="font-weight:700;color:{_NAVY};font-size:0.85rem">{label}</span>'
            )
        else:
            parts_html.append(
                f'<span style="color:{_MUTED};font-size:0.85rem">{label}</span>'
            )
        if not is_last:
            parts_html.append(f'<span style="color:#CBD5E1;padding:0 6px">›</span>')

    st.markdown(
        '<div style="display:flex;align-items:center;padding:6px 0 14px;flex-wrap:wrap">'
        + "".join(parts_html)
        + "</div>",
        unsafe_allow_html=True,
    )

    # Clickable back buttons row (only when not at top level)
    if nav_grade or nav_chapter:
        bcols = st.columns([1.2, 1.2, 8])
        col_idx = 0
        if nav_chapter and bcols[col_idx].button("← All Chapters", key="bc_chapter_btn"):
            _nav_back_to("chapter")
        col_idx += 1
        if nav_grade and bcols[col_idx].button("← All Grades", key="bc_grade_btn"):
            _nav_back_to("grade")


# ── Level 1: Program ───────────────────────────────────────────────────────────

def _render_program_select(df: pd.DataFrame) -> None:
    st.markdown(
        f'<h2 style="margin-bottom:4px;color:{_NAVY}">Select Program</h2>'
        f'<p style="color:{_MUTED};font-size:0.9rem;margin-bottom:28px">'
        f"Choose a curriculum program to explore lesson efficacy data.</p>",
        unsafe_allow_html=True,
    )

    total = len(df)
    good  = len(df[df["RAG"] == "Good"])
    avg   = len(df[df["RAG"] == "Average"])
    bad   = len(df[df["RAG"] == "Bad"])
    pend  = len(df[df["Status"] == "Pending"])

    programs = [("US", "🇺🇸", "United States")]
    future   = [("India", "🇮🇳", "Coming soon"), ("International", "🌍", "Coming soon")]

    c1, c2, c3 = st.columns(3)

    for col, (prog_id, flag, label) in zip([c1], programs):
        with col:
            with st.container(border=True):
                st.markdown(
                    f'<div style="font-size:2.8rem;margin-bottom:10px">{flag}</div>'
                    f'<div style="font-size:1.4rem;font-weight:800;color:{_NAVY};margin-bottom:2px">{prog_id}</div>'
                    f'<div style="font-size:0.8rem;color:{_MUTED};margin-bottom:14px">{label}</div>'
                    f'<div style="font-size:0.75rem;color:{_MUTED};margin-bottom:8px">{total} lesson(s)</div>'
                    + _mini_bar(good, avg, bad, pend)
                    + f'<div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">'
                    + _stat_pill(good, _GREEN, "🟢 ")
                    + _stat_pill(avg, _AMBER, "🟡 ")
                    + _stat_pill(bad, _RED, "🔴 ")
                    + _stat_pill(pend, "#94A3B8", "⏳ ")
                    + "</div>",
                    unsafe_allow_html=True,
                )
                if st.button(f"Open {prog_id} →", key=f"prog_{prog_id}",
                             use_container_width=True, type="primary"):
                    st.session_state["nav_program"] = prog_id
                    st.rerun()

    for col, (prog_id, flag, label) in zip([c2, c3], future):
        with col:
            st.markdown(
                f'<div style="background:#F8FAFC;border-radius:14px;padding:1.4rem;'
                f'border:1px dashed {_BORDER};min-height:200px;display:flex;flex-direction:column;'
                f'justify-content:center;">'
                f'<div style="font-size:2.8rem;margin-bottom:10px">{flag}</div>'
                f'<div style="font-size:1.4rem;font-weight:800;color:{_MUTED};margin-bottom:4px">{prog_id}</div>'
                f'<div style="font-size:0.8rem;color:{_MUTED}">{label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ── Level 2: Grade ─────────────────────────────────────────────────────────────

def _render_grade_select(df: pd.DataFrame) -> None:
    _render_breadcrumb()

    grades = sorted([g for g in df["Grade"].unique() if g])
    if not grades:
        st.info("No grade data available.")
        return

    st.markdown(
        f'<h3 style="margin-bottom:20px;color:{_NAVY}">Select Grade</h3>',
        unsafe_allow_html=True,
    )

    for row_start in range(0, len(grades), 4):
        gcols = st.columns(4)
        for col, grade in zip(gcols, grades[row_start: row_start + 4]):
            gdf   = df[df["Grade"] == grade]
            good  = len(gdf[gdf["RAG"] == "Good"])
            avg   = len(gdf[gdf["RAG"] == "Average"])
            bad   = len(gdf[gdf["RAG"] == "Bad"])
            pend  = len(gdf[gdf["Status"] == "Pending"])
            lbl   = f"Grade {grade}" if str(grade).upper() != "K" else "Grade K"
            slug  = str(grade).replace(" ", "_")

            with col:
                with st.container(border=True):
                    st.markdown(
                        f'<div style="font-size:1.5rem;font-weight:800;color:{_NAVY};margin-bottom:4px">{lbl}</div>'
                        f'<div style="font-size:0.75rem;color:{_MUTED};margin-bottom:10px">{len(gdf)} lesson(s)</div>'
                        + _mini_bar(good, avg, bad, pend)
                        + f'<div style="display:flex;gap:5px;margin-top:6px;flex-wrap:wrap">'
                        + _stat_pill(good, _GREEN, "🟢")
                        + _stat_pill(avg, _AMBER, "🟡")
                        + _stat_pill(bad, _RED, "🔴")
                        + _stat_pill(pend, "#94A3B8", "⏳")
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                    if st.button("View →", key=f"grade_{slug}",
                                 use_container_width=True, type="primary"):
                        st.session_state["nav_grade"] = grade
                        st.rerun()


# ── Level 3: Chapter ───────────────────────────────────────────────────────────

def _render_chapter_select(df: pd.DataFrame, grade: str) -> None:
    _render_breadcrumb()

    gdf      = df[df["Grade"] == grade]
    chapters = sorted([c for c in gdf["Chapter"].unique() if c])

    if not chapters:
        st.info(f"No chapter data for Grade {grade}.")
        return

    grade_lbl = f"Grade {grade}" if str(grade).upper() != "K" else "Grade K"
    st.markdown(
        f'<h3 style="margin-bottom:20px;color:{_NAVY}">{grade_lbl} — {len(chapters)} Chapter(s)</h3>',
        unsafe_allow_html=True,
    )

    for row_start in range(0, len(chapters), 3):
        ccols = st.columns(3)
        for col, chap in zip(ccols, chapters[row_start: row_start + 3]):
            cdf  = gdf[gdf["Chapter"] == chap]
            good = len(cdf[cdf["RAG"] == "Good"])
            avg  = len(cdf[cdf["RAG"] == "Average"])
            bad  = len(cdf[cdf["RAG"] == "Bad"])
            pend = len(cdf[cdf["Status"] == "Pending"])
            slug = (f"ch{grade}_" + chap.replace(" ", "_").replace("/", "_"))[:50]

            with col:
                with st.container(border=True):
                    st.markdown(
                        f'<div style="font-size:1rem;font-weight:700;color:{_NAVY};margin-bottom:4px">{chap}</div>'
                        f'<div style="font-size:0.75rem;color:{_MUTED};margin-bottom:10px">{len(cdf)} lesson(s)</div>'
                        + _mini_bar(good, avg, bad, pend)
                        + f'<div style="display:flex;gap:5px;margin-top:6px;flex-wrap:wrap">'
                        + _stat_pill(good, _GREEN, "🟢")
                        + _stat_pill(avg, _AMBER, "🟡")
                        + _stat_pill(bad, _RED, "🔴")
                        + _stat_pill(pend, "#94A3B8", "⏳")
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                    if st.button("View Lessons →", key=f"chap_{slug}",
                                 use_container_width=True, type="primary"):
                        st.session_state["nav_chapter"] = chap
                        st.rerun()


# ── Level 4: Lesson list ───────────────────────────────────────────────────────

def _render_lesson_list(df: pd.DataFrame, grade: str, chapter: str, on_select_lesson) -> None:
    _render_breadcrumb()

    fdf = df[(df["Grade"] == grade) & (df["Chapter"] == chapter)].copy()

    if fdf.empty:
        st.info("No lessons found in this chapter.")
        return

    good = len(fdf[fdf["RAG"] == "Good"])
    avg  = len(fdf[fdf["RAG"] == "Average"])
    bad  = len(fdf[fdf["RAG"] == "Bad"])
    pend = len(fdf[fdf["Status"] == "Pending"])

    # Summary stat row
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    for col, lbl, val, color in [
        (mc1, "Total",   len(fdf), _NAVY),
        (mc2, "Good",    good,     _GREEN),
        (mc3, "Average", avg,      _AMBER),
        (mc4, "Bad",     bad,      _RED),
        (mc5, "Pending", pend,     "#94A3B8"),
    ]:
        col.markdown(
            f'<div style="background:#fff;border-radius:10px;padding:0.8rem 1rem;'
            f'border:1px solid {_BORDER};border-top:3px solid {color};">'
            f'<div style="font-size:0.65rem;font-weight:700;color:{_MUTED};'
            f'text-transform:uppercase;letter-spacing:0.08em">{lbl}</div>'
            f'<div style="font-size:1.5rem;font-weight:800;color:{color}">{val}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # Lesson cards
    for _, row in fdf.iterrows():
        ref     = row["activity_ref"]
        lesson  = row["Lesson"] or ref
        rag     = row["RAG"]
        color   = _RAG_COLOR.get(rag, "#94A3B8")
        bg      = _RAG_BG.get(rag, "#F8FAFC")
        txt     = _RAG_TEXT.get(rag, "#475569")
        dot     = _RAG_DOT.get(rag, "•")
        summary = row["Summary"] or ""
        teachers = row["Teachers"] or "—"
        rev_date = row["Review Date"] or ""

        lc1, lc2 = st.columns([8, 1])
        with lc1:
            st.markdown(
                f'<div style="background:#fff;border-radius:10px;padding:0.9rem 1.2rem;'
                f'border:1px solid {_BORDER};border-left:4px solid {color};margin-bottom:6px;">'
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
                f'<span style="font-weight:700;color:{_NAVY};font-size:0.95rem">{lesson}</span>'
                f'<span style="background:{bg};color:{txt};border:1px solid {color}44;'
                f'padding:2px 9px 2px 7px;border-radius:12px;font-size:0.72rem;font-weight:700;">'
                f'{dot} {rag}</span>'
                f'</div>'
                f'<div style="font-size:0.75rem;color:{_MUTED}">'
                f'👩‍🏫 {teachers}'
                + (f' &nbsp;·&nbsp; 📅 {rev_date}' if rev_date else "")
                + f'</div>'
                + (f'<div style="font-size:0.75rem;color:{_MUTED};margin-top:3px">{summary}</div>'
                   if summary else "")
                + f'</div>',
                unsafe_allow_html=True,
            )
        with lc2:
            if st.button("Open →", key=f"lesson_{ref}", use_container_width=True):
                on_select_lesson(ref)


# ── Entry point ────────────────────────────────────────────────────────────────

def render_master_view(all_results: dict, on_select_lesson) -> None:
    if not all_results:
        st.info("No lessons yet — click **Refresh Data** in the sidebar.")
        return

    df = _build_df(all_results)

    nav_program = st.session_state.get("nav_program")
    nav_grade   = st.session_state.get("nav_grade")
    nav_chapter = st.session_state.get("nav_chapter")

    if not nav_program:
        _render_program_select(df)
    elif not nav_grade:
        _render_grade_select(df)
    elif not nav_chapter:
        _render_chapter_select(df, nav_grade)
    else:
        _render_lesson_list(df, nav_grade, nav_chapter, on_select_lesson)


# ── Helpers reused by pdf_export / app sidebar ────────────────────────────────

def build_tutor_df(all_results: dict) -> "pd.DataFrame":
    rows = []
    for ref, res in all_results.items():
        names   = res.get("teacher_names") or []
        ratings = res.get("teacher_ratings") or []
        for idx, name in enumerate(names):
            if not name:
                continue
            rows.append({
                "Tutor":        name,
                "Grade":        (res.get("grade") or "").strip(),
                "Chapter":      (res.get("chapter") or "").strip(),
                "Lesson":       (res.get("lesson") or ref).strip(),
                "activity_ref": ref,
                "Rating":       safe_float(ratings[idx]) if idx < len(ratings) else 0.0,
                "RAG":          res.get("final_rating", "Pending"),
                "Review Date":  res.get("review_date", ""),
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Tutor", "Grade", "Chapter", "Lesson", "activity_ref", "Rating", "RAG", "Review Date"]
    )
