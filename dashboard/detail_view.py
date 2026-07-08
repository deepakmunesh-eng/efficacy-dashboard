"""Lesson Detail View — section tabs (Learning / Practice / Exit)."""
from __future__ import annotations

import streamlit as st


@st.cache_data(ttl=3600)
def _load_ai_reviews() -> dict:
    try:
        from data.ai_review_reader import fetch_ai_reviews
        return fetch_ai_reviews()
    except Exception:
        return {}

from config.settings import LEARNOSITY_VIEWER_URL
from dashboard.components import pending_banner, error_banner, verdict_card, section_header
from utils.helpers import safe_float
from utils.cache import get_curriculum_review, store_curriculum_review

_NAVY   = "#0E1B3D"
_GREEN  = "#2DBD6E"
_AMBER  = "#F59E0B"
_RED    = "#E84C3D"
_MUTED  = "#5B6B82"
_BORDER = "#E4EAF3"

_RAG_COLOR = {"Good": _GREEN, "Average": _AMBER, "Bad": _RED, "Pending": "#94A3B8", "N/A": "#94A3B8", "—": "#94A3B8"}
_RAG_BG    = {"Good": "#EDFAF3", "Average": "#FFF8EB", "Bad": "#FEF1F1", "Pending": "#F8FAFC", "N/A": "#F8FAFC", "—": "#F8FAFC"}
_RAG_TEXT  = {"Good": "#156D3E", "Average": "#8A5800", "Bad": "#9B1C1C", "Pending": "#475569", "N/A": "#475569", "—": "#475569"}
_RAG_DOT   = {"Good": "🟢", "Average": "🟡", "Bad": "🔴", "Pending": "⏳", "N/A": "—", "—": "—"}

_ACTION_TYPES = [
    "—",
    "Fix content / visuals",
    "Add guided example",
    "Revise instructions",
    "Replace item",
    "Adjust difficulty level",
    "Fix language / terminology",
    "Other",
]


# ── Utility components ─────────────────────────────────────────────────────────

def _rag_pill(rating: str, size: str = "normal") -> str:
    c  = _RAG_COLOR.get(rating, "#94A3B8")
    bg = _RAG_BG.get(rating, "#F8FAFC")
    t  = _RAG_TEXT.get(rating, "#475569")
    d  = _RAG_DOT.get(rating, "•")
    fs = "0.85rem" if size == "normal" else "0.72rem"
    return (
        f'<span style="background:{bg};color:{t};border:1px solid {c}44;'
        f'padding:3px 10px 3px 7px;border-radius:20px;font-size:{fs};font-weight:700;'
        f'display:inline-flex;align-items:center;gap:4px;">{d} {rating}</span>'
    )


def _section_card(label: str, rating: str, score: float, rationale: str) -> str:
    c  = _RAG_COLOR.get(rating, "#94A3B8")
    bg = _RAG_BG.get(rating, "#F8FAFC")
    t  = _RAG_TEXT.get(rating, "#475569")
    d  = _RAG_DOT.get(rating, "•")
    return (
        f'<div style="background:{bg};border-radius:12px;padding:1.1rem 1.3rem;'
        f'border:1px solid {c}33;border-left:4px solid {c};margin-bottom:16px;">'
        f'<div style="font-size:0.68rem;font-weight:700;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:0.08em;margin-bottom:6px">{label} Section</div>'
        f'<div style="display:flex;align-items:center;gap:12px">'
        f'<span style="font-size:2rem;font-weight:800;color:{c}">{score:.1f}'
        f'<span style="font-size:0.75rem;font-weight:500;color:{_MUTED}">/5</span></span>'
        f'<div>'
        f'<span style="background:{bg};color:{t};border:1px solid {c}44;'
        f'padding:2px 10px 2px 7px;border-radius:12px;font-size:0.8rem;font-weight:700;">'
        f'{d} {rating}</span>'
        f'<div style="font-size:0.75rem;color:{_MUTED};margin-top:4px;line-height:1.4">{rationale[:220]}</div>'
        f'</div></div></div>'
    )


_RATING_GUIDE = {
    "Learning": {
        "weight": 40,
        "formula": (
            "**Per-item score** = weighted average of 3 teachers:\n"
            "- Understanding 30% · Engagement 30% · Examples 25%\n"
            "- Language 10% · Length 5%\n\n"
            "−0.2 per diverging dimension between teachers.\n\n"
            "**Section score** = average of all item scores.\n\n"
            "🟢 Good ≥ 4.0 · 🟡 Average 3.0–3.9 · 🔴 Bad < 3.0"
        ),
    },
    "Practice": {
        "weight": 20,
        "formula": (
            "**Score** = average of teacher practice quality ratings.\n\n"
            "Ratings: Excellent 5 · Good 4 · Satisfactory 3 · Needs Work 2 · Poor 1\n\n"
            "🟢 Good ≥ 4.0 · 🟡 Average 3.0–3.9 · 🔴 Bad < 3.0"
        ),
    },
    "Exit Ticket": {
        "weight": 10,
        "formula": (
            "**Score** = average of teacher exit ticket quality ratings.\n\n"
            "Ratings: Excellent 5 · Good 4 · Satisfactory 3 · Needs Work 2 · Poor 1\n\n"
            "🟢 Good ≥ 4.0 · 🟡 Average 3.0–3.9 · 🔴 Bad < 3.0"
        ),
    },
}


def _render_rating_guide_popover(section: str) -> None:
    """Small ℹ️ button that opens a popover explaining the rating formula."""
    guide = _RATING_GUIDE.get(section, {})
    if not guide:
        return
    with st.popover("ℹ️", use_container_width=False):
        st.markdown(f"#### {section} Rating Guide")
        st.markdown(
            f"Contributes **{guide['weight']}%** to the final lesson rating.\n\n"
            + guide["formula"]
        )
        st.markdown(
            "---\n**Final lesson rating weights:**  \n"
            "Learning 40% · Practice 20% · Exit Ticket 10% · Classroom 30%"
        )


# ── Back navigation ────────────────────────────────────────────────────────────

def _render_back_nav(lesson_name: str) -> None:
    nav_program = st.session_state.get("nav_program", "US")
    nav_grade   = st.session_state.get("nav_grade", "")
    nav_chapter = st.session_state.get("nav_chapter", "")

    # Back button
    if st.button("← Back to Chapter", key="dv_back_btn"):
        st.session_state.pop("selected_lesson", None)
        st.rerun()

    # Static breadcrumb path
    parts = [p for p in [nav_program,
                         (f"Grade {nav_grade}" if nav_grade else ""),
                         nav_chapter,
                         lesson_name] if p]
    crumb_html = " <span style='color:#CBD5E1;padding:0 4px'>›</span> ".join(
        f'<span style="{"font-weight:700;color:" + _NAVY if i == len(parts)-1 else "color:" + _MUTED};font-size:0.82rem">{p}</span>'
        for i, p in enumerate(parts)
    )
    st.markdown(
        f'<div style="padding:4px 0 14px;display:flex;align-items:center;flex-wrap:wrap">'
        f'{crumb_html}</div>',
        unsafe_allow_html=True,
    )


# ── Learning section ───────────────────────────────────────────────────────────

def _render_teacher_summary_col(t_data: dict) -> None:
    name     = t_data.get("name", "Teacher") or "Teacher"
    summary  = t_data.get("summary", "") or ""
    concerns = t_data.get("key_concerns", "") or ""

    # Build entire column as one HTML block to avoid per-part st calls.
    html = (
        f'<div style="font-size:0.85rem;font-weight:700;color:{_NAVY};margin-bottom:8px">'
        f'👩‍🏫 {name}</div>'
    )

    if summary and summary != "No detailed feedback provided.":
        for part in summary.split(" | "):
            part = part.strip()
            if not part:
                continue
            if ": " in part:
                lbl, val = part.split(": ", 1)
                html += (
                    f'<div style="margin-bottom:4px">'
                    f'<span style="font-size:0.7rem;font-weight:700;color:{_MUTED};'
                    f'text-transform:uppercase;letter-spacing:0.05em">{lbl}</span> '
                    f'<span style="font-size:0.78rem;color:{_NAVY}">{val}</span></div>'
                )
            else:
                html += (
                    f'<div style="font-size:0.78rem;color:{_MUTED};margin-bottom:2px">'
                    f'{part[:160]}</div>'
                )
    else:
        html += (
            f'<div style="font-size:0.78rem;color:{_MUTED};font-style:italic">'
            f'No detailed feedback recorded.</div>'
        )

    if concerns:
        html += (
            f'<div style="background:#FEF2F2;border-radius:6px;padding:4px 8px;margin-top:6px;'
            f'font-size:0.72rem;color:#9B1C1C">⚠️ {concerns}</div>'
        )

    st.markdown(html, unsafe_allow_html=True)


def _synthesize_teacher_analysis(teacher_summaries: dict) -> list[tuple[str, str, bool]]:
    """Group teacher feedback by dimension for the consolidated view.

    Returns (dimension, combined_text, diverges) tuples. The per-part
    "Dimension: " prefix is stripped (the dimension is already the label, so we
    don't want "Length: Length: ..."). When teachers give different answers for
    the same dimension, `diverges` is True so the UI can flag the disagreement.
    """
    buckets: dict[str, list[str]] = {
        "Understanding": [], "Engagement": [], "Examples": [],
        "Length": [], "Language": [], "Other": [],
    }
    for t_data in teacher_summaries.values():
        summary = t_data.get("summary", "") or ""
        for part in summary.split(" | "):
            part = part.strip()
            if not part or part == "No detailed feedback provided.":
                continue
            matched = False
            for key in ("Understanding", "Engagement", "Examples", "Length", "Language"):
                if key.lower() in part.lower():
                    # Drop the leading "Key: " label so it isn't shown twice.
                    val = part.split(":", 1)[1].strip() if ":" in part else part
                    if val:
                        buckets[key].append(val)
                    matched = True
                    break
            if not matched:
                buckets["Other"].append(part)

    result = []
    for dim, items in buckets.items():
        if not items:
            continue
        unique = list(dict.fromkeys(items))
        diverges = len(unique) > 1
        result.append((dim, " · ".join(unique[:4]), diverges))
    return result


def _render_ai_consolidated_summary(
    item_ref: str,
    teacher_summaries: dict,
    ai_reviews: dict,
) -> None:
    st.markdown(
        f'<div style="font-size:0.8rem;font-weight:700;color:{_NAVY};margin-bottom:10px">'
        f'AI Consolidated Summary</div>',
        unsafe_allow_html=True,
    )

    # Build the teacher analysis (full width — the "Expert AI Review" column was
    # removed). Divergent dimensions are flagged so it's clear when teachers
    # disagree instead of showing the same label twice.
    analysis = _synthesize_teacher_analysis(teacher_summaries)
    teacher_html = (
        f'<div style="font-size:0.7rem;font-weight:700;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:0.07em;margin-bottom:8px">Teacher Analysis</div>'
    )
    if analysis:
        for dim, text, diverges in analysis:
            div_tag = (
                f'<span style="background:#FEF3C7;color:#8A5800;border:1px solid #F5D98B;'
                f'padding:0 7px;border-radius:20px;font-size:0.62rem;font-weight:700;'
                f'margin-left:6px;white-space:nowrap">⚠ teachers differ</span>'
                if diverges else ""
            )
            teacher_html += (
                f'<div style="margin-bottom:5px">'
                f'<span style="font-size:0.7rem;font-weight:700;color:{_MUTED};text-transform:uppercase">'
                f'{dim}:</span> '
                f'<span style="font-size:0.78rem;color:{_NAVY}">{text}</span>{div_tag}</div>'
            )
    else:
        teacher_html += (
            f'<div style="font-size:0.78rem;color:{_MUTED};font-style:italic">'
            f'No teacher analysis available.</div>'
        )
    st.markdown(teacher_html, unsafe_allow_html=True)


def _render_curriculum_review_tab(
    activity_ref: str,
    flow_a: list,
    sr: dict,
) -> None:
    """Single consolidated curriculum review — section-wise action plan.

    One form covers Learning / Practice / Exit Ticket, saved in one shot.
    """
    cr_key = f"{activity_ref}|curriculum_review"
    saved  = get_curriculum_review(cr_key)
    prio_opts = ["—", "High", "Medium", "Low"]

    # Show last-saved timestamp
    if saved.get("_saved_at"):
        import datetime as _dt
        ts = _dt.datetime.fromtimestamp(saved["_saved_at"]).strftime("%d %b %Y, %H:%M")
        st.markdown(
            f'<div style="font-size:0.72rem;color:{_MUTED};margin-bottom:18px">'
            f'Last saved: {ts}</div>',
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    def _section_block(section_key: str, label: str, icon: str,
                       score: float, rating: str, items: list) -> dict:
        """Render one section block and return its form values."""
        s = saved.get(section_key, {})
        color   = _RAG_COLOR.get(rating, "#94A3B8")
        bg      = _RAG_BG.get(rating, "#F8FAFC")
        txt     = _RAG_TEXT.get(rating, "#475569")
        dot     = _RAG_DOT.get(rating, "•")

        # Section header pill
        st.markdown(
            f'<div style="border-radius:10px;border:1.5px solid {color}44;border-left:4px solid {color};'
            f'background:{bg};padding:12px 16px;margin-bottom:14px;display:flex;align-items:center;gap:12px">'
            f'<span style="font-size:1rem;font-weight:700;color:{_NAVY}">{icon} {label}</span>'
            f'<span style="font-size:0.82rem;font-weight:700;color:{txt}">'
            f'{dot} {rating} · {score:.1f}/5</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Item rating badges (Learning only)
        if items and section_key == "learning":
            badges = []
            for item in items:
                iref  = item.get("item_ref", "?")
                irat  = item.get("rating", "?")
                isc   = float(item.get("score", 0))
                ibg   = _RAG_BG.get(irat, "#F8FAFC")
                ic    = _RAG_COLOR.get(irat, "#94A3B8")
                short = iref.split(".")[-1] if "." in iref else iref
                badges.append(
                    f'<span style="background:{ibg};border:1px solid {ic}55;border-radius:6px;'
                    f'padding:2px 9px;font-size:0.72rem;margin-right:5px;white-space:nowrap">'
                    f'{short} {_RAG_DOT.get(irat,"•")} {isc:.1f}</span>'
                )
            if badges:
                st.markdown(
                    '<div style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:4px">'
                    + "".join(badges) + "</div>",
                    unsafe_allow_html=True,
                )

        need_action = st.radio(
            "Action needed?",
            ["No action needed", "Yes — action required"],
            index=1 if s.get("action_needed") else 0,
            horizontal=True,
            key=f"cr_{section_key}_need_{activity_ref}",
        )

        action_type      = "—"
        priority         = "—"
        items_to_address: list = []

        if need_action == "Yes — action required":
            col_a, col_b = st.columns(2)

            saved_type = s.get("action_type", "—")
            type_idx   = _ACTION_TYPES.index(saved_type) if saved_type in _ACTION_TYPES else 0
            with col_a:
                action_type = st.selectbox(
                    "Action type",
                    _ACTION_TYPES,
                    index=type_idx,
                    key=f"cr_{section_key}_type_{activity_ref}",
                )

            saved_prio = s.get("priority", "—")
            prio_idx   = prio_opts.index(saved_prio) if saved_prio in prio_opts else 0
            with col_b:
                priority = st.selectbox(
                    "Priority",
                    prio_opts,
                    index=prio_idx,
                    key=f"cr_{section_key}_prio_{activity_ref}",
                )

            # Item picker for learning section
            if items and section_key == "learning":
                labels = []
                for item in items:
                    iref  = item.get("item_ref", "")
                    short = iref.split(".")[-1] if "." in iref else iref
                    labels.append(short)
                prev = [x for x in s.get("items_to_address", []) if x in labels]
                items_to_address = st.multiselect(
                    "Items to address",
                    labels,
                    default=prev,
                    key=f"cr_{section_key}_items_{activity_ref}",
                    help="Select which items specifically need changes",
                )

        notes = st.text_area(
            "Detailed notes",
            value=s.get("notes", ""),
            height=110,
            placeholder=f"Describe exactly what needs to change in the {label.lower()}…",
            key=f"cr_{section_key}_notes_{activity_ref}",
        )

        return {
            "action_needed":    need_action == "Yes — action required",
            "action_type":      action_type,
            "priority":         priority,
            "items_to_address": items_to_address,
            "notes":            notes,
        }
    # ------------------------------------------------------------------

    lr = sr.get("learning",    {})
    pr = sr.get("practice",    {})
    et = sr.get("exit_ticket", {})

    learning_vals = _section_block(
        "learning", "Learning Section", "📖",
        float(lr.get("score", 0)), lr.get("rating", "—"), flow_a,
    )

    st.divider()

    practice_vals = _section_block(
        "practice", "Practice Section", "✏️",
        float(pr.get("score", 0)), pr.get("rating", "—"), [],
    )

    st.divider()

    exit_vals = _section_block(
        "exit_ticket", "Exit Ticket Section", "🎯",
        float(et.get("score", 0)), et.get("rating", "—"), [],
    )

    st.divider()

    # Overall notes
    st.markdown(
        f'<div style="font-size:0.88rem;font-weight:700;color:{_NAVY};margin-bottom:8px">'
        f'📝 Overall Notes</div>',
        unsafe_allow_html=True,
    )
    overall_notes = st.text_area(
        "overall_notes",
        value=saved.get("overall_notes", ""),
        height=90,
        placeholder="Any cross-cutting notes or instructions for the curriculum team…",
        key=f"cr_overall_{activity_ref}",
        label_visibility="collapsed",
    )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    save_col, clear_col, _ = st.columns([2, 2, 8])
    with save_col:
        if st.button("💾  Save Review", key=f"cr_save_all_{activity_ref}",
                     use_container_width=True, type="primary"):
            store_curriculum_review(cr_key, {
                "learning":      learning_vals,
                "practice":      practice_vals,
                "exit_ticket":   exit_vals,
                "overall_notes": overall_notes,
                "activity_ref":  activity_ref,
            })
            st.success("Curriculum review saved!")
    with clear_col:
        if st.button("🗑️  Clear All", key=f"cr_clear_all_{activity_ref}",
                     use_container_width=True):
            store_curriculum_review(cr_key, {})
            st.rerun()


def _render_learning_item_card(
    item_result: dict,
    activity_ref: str,
    ai_reviews: dict,
    idx: int,
) -> None:
    item_ref  = item_result.get("item_ref", "?")
    rating    = item_result.get("rating", "?")
    score     = float(item_result.get("score", 0.0))
    rationale = item_result.get("rationale", "")
    teacher_summaries = item_result.get("teacher_summaries", {}) or {}
    divergences       = item_result.get("divergences", []) or []
    teacher_count     = item_result.get("teacher_count", len(teacher_summaries))

    color = _RAG_COLOR.get(rating, "#94A3B8")
    dot   = _RAG_DOT.get(rating, "•")

    # Show how many teachers reviewed THIS item (transparency — items can have
    # fewer than 3 reviews). Amber tint when fewer than 3.
    tc_color = _MUTED if teacher_count >= 3 else _AMBER
    tc_chip = (
        f'<span style="font-size:0.72rem;font-weight:600;color:{tc_color}">'
        f'· {teacher_count} teacher{"s" if teacher_count != 1 else ""}</span>'
    )

    with st.container(border=True):
        # ── Item header ───────────────────────────────────────────────────────
        h_left, h_right = st.columns([7, 2])
        with h_left:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
                f'<span style="font-size:0.95rem;font-weight:700;color:{_NAVY}">{item_ref}</span>'
                + _rag_pill(rating)
                + (f'<span style="font-size:0.9rem;font-weight:800;color:{color}">'
                   f'{score:.1f}<span style="font-size:0.7rem;font-weight:500;color:{_MUTED}">/5</span></span>'
                   if score > 0 else "")
                + tc_chip
                + "</div>",
                unsafe_allow_html=True,
            )
        with h_right:
            # Learnosity item link removed until content access is available.
            st.empty()

        if rationale:
            st.caption(rationale)

        if divergences:
            dims = ", ".join(d.get("dimension", "") for d in divergences if d.get("dimension"))
            st.warning(f"⚠️ Teacher divergence on: {dims}")

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        # ── 3 Teacher Summaries ───────────────────────────────────────────────
        st.markdown(
            f'<div style="font-size:0.8rem;font-weight:700;color:{_NAVY};margin-bottom:10px">'
            f'Teacher Summaries</div>',
            unsafe_allow_html=True,
        )
        t_items = list(teacher_summaries.items())
        if t_items:
            t_cols = st.columns(len(t_items))
            for col, (_, t_data) in zip(t_cols, t_items):
                with col:
                    _render_teacher_summary_col(t_data)
        else:
            st.caption("No teacher summary data available.")

        st.divider()

        # ── AI Consolidated Summary ───────────────────────────────────────────
        # (The item's rating is already shown in the header — no duplicate
        # "Final Rating" row here; the overall Learning-section rating is shown
        # at the top of the section.)
        _render_ai_consolidated_summary(item_ref, teacher_summaries, ai_reviews)

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)


def _render_unreviewed_item_card(
    item_ref: str, activity_ref: str, ai_reviews: dict, idx: int
) -> None:
    """Card for a Learnosity item that has no teacher reviews yet."""
    with st.container(border=True):
        h_left, h_right = st.columns([7, 2])
        with h_left:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
                f'<span style="font-size:0.95rem;font-weight:700;color:{_NAVY}">{item_ref}</span>'
                f'<span style="background:#F1F5F9;color:#64748B;border:1px solid #CBD5E1;'
                f'padding:3px 10px;border-radius:20px;font-size:0.78rem;font-weight:600">'
                f'⏳ Awaiting review</span></div>',
                unsafe_allow_html=True,
            )
        with h_right:
            # Learnosity item link removed until content access is available.
            st.empty()

        st.caption("No teacher reviews submitted for this item yet.")
        st.divider()


def _render_learning_section(
    flow_a: list,
    per_teacher: list,
    section_data: dict,
    activity_ref: str,
    ai_reviews: dict,
) -> None:
    score     = float(section_data.get("score", 0.0))
    rating    = section_data.get("rating", "—")
    rationale = section_data.get("rationale", "")

    # Section overview card + rating guide icon
    card_col, guide_col = st.columns([20, 1])
    with card_col:
        if rating != "—":
            st.markdown(_section_card("Learning", rating, score, rationale), unsafe_allow_html=True)
    with guide_col:
        _render_rating_guide_popover("Learning")

    # Fetch any additional items from Railway (when auth token is set)
    from utils.auth import get_effective_auth_token
    auth_token = get_effective_auth_token(st.session_state.get("railway_auth_token", ""))
    railway_refs: list[str] = []
    if auth_token:
        cache_key = f"_railway_{activity_ref}"
        if cache_key not in st.session_state:
            with st.spinner("Fetching items from Learnosity…"):
                from data.learnosity_client import fetch_activity_items
                railway_refs = fetch_activity_items(activity_ref, auth_token)
                st.session_state[cache_key] = railway_refs
        else:
            railway_refs = st.session_state[cache_key]

    # Items in flow_a that have teacher reviews
    reviewed_refs = {r["item_ref"] for r in flow_a}
    # Items from Railway not yet in the review sheet
    unreviewed_refs = [r for r in railway_refs if r not in reviewed_refs]

    total_items = len(flow_a) + len(unreviewed_refs)

    if railway_refs:
        st.markdown(
            f'<div style="font-size:0.78rem;color:{_MUTED};margin-bottom:12px">'
            f'<b>{total_items}</b> items in Learnosity · '
            f'<b style="color:{_GREEN}">{len(flow_a)}</b> reviewed · '
            f'<b style="color:{_AMBER}">{len(unreviewed_refs)}</b> pending teacher review</div>',
            unsafe_allow_html=True,
        )
    else:
        if not flow_a:
            st.info("No learning item data available. Add an auth token in the sidebar to load items from Learnosity.")
            return
        st.markdown(
            f'<div style="font-size:0.78rem;color:{_MUTED};margin-bottom:12px">'
            f'<b>{len(flow_a)}</b> reviewed item(s)'
            + (' · <span style="font-size:0.72rem;font-style:italic">Add auth token to see all Learnosity items</span>' if not auth_token else '')
            + '</div>',
            unsafe_allow_html=True,
        )

    for idx, item_result in enumerate(flow_a):
        _render_learning_item_card(item_result, activity_ref, ai_reviews, idx)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    if unreviewed_refs:
        st.markdown(
            f'<div style="font-size:0.8rem;font-weight:700;color:{_AMBER};margin:16px 0 8px">'
            f'⏳ {len(unreviewed_refs)} item(s) not yet reviewed by teachers</div>',
            unsafe_allow_html=True,
        )
        for idx, item_ref in enumerate(unreviewed_refs, start=len(flow_a)):
            _render_unreviewed_item_card(item_ref, activity_ref, ai_reviews, idx)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)


# ── Practice & Exit sections ───────────────────────────────────────────────────

def _render_teacher_section_feedback(
    per_teacher: list,
    quality_field: str,
    obs_field: str,
) -> None:
    if not per_teacher:
        st.caption("No teacher feedback data available.")
        return

    cols = st.columns(min(len(per_teacher), 3))
    for col, row in zip(cols, per_teacher[:3]):
        with col:
            name = (row.get("reviewer_name") or "Teacher").strip()
            qual = (row.get(quality_field) or "").strip()
            obs  = (row.get(obs_field) or "").strip()

            html = (
                f'<div style="font-size:0.85rem;font-weight:700;color:{_NAVY};margin-bottom:8px">'
                f'👩‍🏫 {name}</div>'
            )
            if qual:
                html += (
                    f'<span style="background:#F4F6FF;border:1px solid {_BORDER};'
                    f'border-radius:6px;padding:2px 8px;font-size:0.72rem;color:{_NAVY}">'
                    f'<b>Quality:</b> {qual}</span>'
                )
            if obs:
                html += (
                    f'<div style="font-size:0.78rem;color:{_MUTED};margin-top:6px">'
                    f'Observations: {obs[:300]}</div>'
                )
            if not qual and not obs:
                html += (
                    f'<div style="font-size:0.78rem;color:{_MUTED};font-style:italic">'
                    f'No feedback recorded.</div>'
                )
            st.markdown(html, unsafe_allow_html=True)


def _render_practice_section(per_teacher: list, section_data: dict) -> None:
    score     = float(section_data.get("score", 0.0))
    rating    = section_data.get("rating", "—")
    rationale = section_data.get("rationale", "")

    card_col, guide_col = st.columns([20, 1])
    with card_col:
        if rating != "—":
            st.markdown(_section_card("Practice", rating, score, rationale), unsafe_allow_html=True)
    with guide_col:
        _render_rating_guide_popover("Practice")

    st.markdown(
        f'<div style="font-size:0.8rem;font-weight:700;color:{_NAVY};margin-bottom:10px">'
        f'Teacher Observations</div>',
        unsafe_allow_html=True,
    )
    _render_teacher_section_feedback(per_teacher, "practice_quality", "practice_observations")


def _render_exit_section(per_teacher: list, section_data: dict) -> None:
    score     = float(section_data.get("score", 0.0))
    rating    = section_data.get("rating", "—")
    rationale = section_data.get("rationale", "")

    card_col, guide_col = st.columns([20, 1])
    with card_col:
        if rating != "—":
            st.markdown(_section_card("Exit Ticket", rating, score, rationale), unsafe_allow_html=True)
    with guide_col:
        _render_rating_guide_popover("Exit Ticket")

    st.markdown(
        f'<div style="font-size:0.8rem;font-weight:700;color:{_NAVY};margin-bottom:10px">'
        f'Teacher Observations</div>',
        unsafe_allow_html=True,
    )
    _render_teacher_section_feedback(per_teacher, "exit_ticket_quality", "exit_ticket_observations")


# ── AI Expert Review tab ──────────────────────────────────────────────────────

def _render_ai_expert_review_tab(ai_review: dict) -> None:
    """Full AI Expert Review panel shown in its own tab."""
    if not ai_review:
        st.info("AI expert review not yet generated. Refresh data to trigger.")
        return

    if ai_review.get("error"):
        err = ai_review["error"]
        if "ANTHROPIC_API_KEY" in err:
            st.warning(
                "**AI Expert Review requires `ANTHROPIC_API_KEY`** — "
                "add it to Railway environment variables for this service."
            )
        elif "LEARNOSITY_CONSUMER_KEY" in err or "Learnosity" in err:
            st.warning(
                "**Learnosity content unavailable** — "
                "add `LEARNOSITY_CONSUMER_KEY` and `LEARNOSITY_CONSUMER_SECRET` to Railway env vars. "
                "Review is based on teacher feedback only."
            )
        else:
            st.error(f"AI review error: {err}")
        return

    final_rating = ai_review.get("final_rating", "—")
    summary      = ai_review.get("overall_summary", "")
    strengths    = ai_review.get("strengths", [])
    concerns     = ai_review.get("concerns", [])
    recs         = ai_review.get("recommendations", [])
    confidence   = ai_review.get("confidence", "")
    conf_note    = ai_review.get("confidence_note", "")
    items_found  = ai_review.get("_learnosity_found", False)
    gen_at       = ai_review.get("_generated_at", 0)

    c  = _RAG_COLOR.get(final_rating, "#94A3B8")
    bg = _RAG_BG.get(final_rating, "#F8FAFC")
    t  = _RAG_TEXT.get(final_rating, "#475569")
    d  = _RAG_DOT.get(final_rating, "•")

    # Hero rating card
    conf_color = {"High": _GREEN, "Medium": _AMBER, "Low": _RED}.get(confidence, _MUTED)
    items_badge = (
        f'<span style="font-size:0.72rem;color:{_GREEN};font-weight:600">✓ Learnosity content included</span>'
        if items_found else
        f'<span style="font-size:0.72rem;color:{_AMBER};font-weight:600">⚠ Based on teacher feedback only (Learnosity unavailable)</span>'
    )

    import datetime as _dt
    try:
        gen_str = _dt.datetime.fromtimestamp(gen_at).strftime("%d %b %Y, %H:%M") if gen_at else "—"
    except Exception:
        gen_str = "—"

    conf_span = (
        f'<span style="font-size:0.72rem;font-weight:700;color:{conf_color}">'
        f'{confidence} confidence</span>'
        if confidence else ""
    )
    conf_note_span = (
        f'<span style="font-size:0.72rem;color:{_MUTED};font-style:italic">{conf_note}</span>'
        if conf_note else ""
    )

    # Slim context line only — the headline rating + section scores are shown by
    # the rating bar rendered just above this panel (AI review tab).
    st.markdown(
        f'<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:16px">'
        f'{items_badge}'
        f'<span style="font-size:0.68rem;color:{_MUTED}">Generated {gen_str}</span>'
        f'{conf_span}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Strengths + Concerns side by side
    col_s, col_c = st.columns(2)
    with col_s:
        if strengths:
            s_html = (
                f'<div style="font-size:0.7rem;font-weight:700;color:{_MUTED};text-transform:uppercase;'
                f'letter-spacing:0.07em;margin-bottom:8px">Strengths</div>'
            ) + "".join(
                f'<div style="display:flex;gap:8px;margin-bottom:6px">'
                f'<span style="color:{_GREEN};font-size:0.9rem;flex-shrink:0">✓</span>'
                f'<span style="font-size:0.82rem;color:{_NAVY}">{s}</span></div>'
                for s in strengths
            )
            st.markdown(s_html, unsafe_allow_html=True)

    with col_c:
        if concerns:
            c_html = (
                f'<div style="font-size:0.7rem;font-weight:700;color:{_MUTED};text-transform:uppercase;'
                f'letter-spacing:0.07em;margin-bottom:8px">Needs curriculum intervention</div>'
            ) + "".join(
                f'<div style="display:flex;gap:8px;margin-bottom:6px">'
                f'<span style="color:{_AMBER};font-size:0.9rem;flex-shrink:0">●</span>'
                f'<span style="font-size:0.82rem;color:{_NAVY}">{c_item}</span></div>'
                for c_item in concerns
            )
            st.markdown(c_html, unsafe_allow_html=True)

    # Recommendations — hidden for now (flip to True to restore)
    _SHOW_RECOMMENDATIONS = False
    if _SHOW_RECOMMENDATIONS and recs:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        r_html = (
            f'<div style="font-size:0.7rem;font-weight:700;color:{_MUTED};text-transform:uppercase;'
            f'letter-spacing:0.07em;margin-bottom:8px">Recommendations</div>'
        ) + "".join(
            f'<div style="background:#F4F6FF;border-radius:8px;padding:8px 12px;margin-bottom:6px;'
            f'display:flex;gap:10px;align-items:flex-start">'
            f'<span style="font-size:0.78rem;font-weight:700;color:{_NAVY};flex-shrink:0">{i+1}.</span>'
            f'<span style="font-size:0.82rem;color:{_NAVY}">{r}</span></div>'
            for i, r in enumerate(recs)
        )
        st.markdown(r_html, unsafe_allow_html=True)


# ── Lesson-level rating bar (above tabs) ──────────────────────────────────────

def _render_lesson_rating_bar(result: dict) -> None:
    """Compact bar showing the final lesson rating + section breakdown.

    Prefers the AI Expert rating when available; falls back to teacher consensus.
    Shown above the tabs so it stays in view as the user scrolls through content.
    """
    ai_review    = result.get("ai_expert_review") or {}
    ai_rating    = ai_review.get("final_rating") if not ai_review.get("error") else None

    final_rating = ai_rating or result.get("final_rating", "Pending")
    status       = result.get("status", "Pending")
    sr           = result.get("section_ratings") or {}
    summary      = (ai_review.get("overall_summary") or result.get("one_line_summary", ""))
    score        = result.get("weighted_score", 0.0)
    label        = "AI Expert Rating" if ai_rating else "Lesson Final Rating"

    c  = _RAG_COLOR.get(final_rating, "#94A3B8")
    bg = _RAG_BG.get(final_rating, "#F8FAFC")
    t  = _RAG_TEXT.get(final_rating, "#475569")
    d  = _RAG_DOT.get(final_rating, "•")

    # Section mini-scores
    section_items = [
        ("Learning",     sr.get("learning",    {}).get("score", 0), sr.get("learning",    {}).get("rating", "—")),
        ("Practice",     sr.get("practice",    {}).get("score", 0), sr.get("practice",    {}).get("rating", "—")),
        ("Exit Ticket",  sr.get("exit_ticket", {}).get("score", 0), sr.get("exit_ticket", {}).get("rating", "—")),
    ]
    section_html = ""
    for lbl, sc, rat in section_items:
        sc2   = _RAG_COLOR.get(rat, "#94A3B8")
        sc_bg = _RAG_BG.get(rat, "#F8FAFC")
        sc_t  = _RAG_TEXT.get(rat, "#475569")
        val   = f"{sc:.1f}/5" if sc else "—"
        section_html += (
            f'<div style="display:flex;flex-direction:column;align-items:center;'
            f'background:{sc_bg};border:1px solid {sc2}33;border-radius:8px;'
            f'padding:6px 14px;min-width:80px">'
            f'<span style="font-size:0.65rem;font-weight:700;color:{_MUTED};'
            f'text-transform:uppercase;letter-spacing:0.06em">{lbl}</span>'
            f'<span style="font-size:0.9rem;font-weight:800;color:{sc2}">{val}</span>'
            f'</div>'
        )

    pending_note = (
        f'<span style="font-size:0.75rem;color:{_MUTED};font-style:italic;margin-left:10px">'
        f'(preliminary — awaiting more reviews)</span>'
        if status == "Pending" else ""
    )
    score_display = f'<span style="font-size:1rem;font-weight:700;color:{_MUTED};margin:0 14px">{score:.2f}/5</span>' if score else ""

    # Summary text intentionally omitted here — the full detail lives in the
    # Strengths / "Needs curriculum intervention" lists (no more half-cut lines).
    summary_line = ""
    st.markdown(
        f'<div style="background:{bg};border:1.5px solid {c}44;border-left:5px solid {c};'
        f'border-radius:0 12px 12px 0;padding:12px 18px;margin-bottom:16px;'
        f'display:flex;align-items:center;flex-wrap:wrap;gap:12px">'
        f'<div style="display:flex;flex-direction:column;min-width:120px">'
        f'<span style="font-size:0.65rem;font-weight:700;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:0.08em;margin-bottom:3px">{label}</span>'
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<span style="font-size:1.5rem;font-weight:800;color:{t}">{d} {final_rating}</span>'
        f'{score_display}'
        f'{pending_note}'
        f'</div>'
        f'{summary_line}'
        f'</div>'
        f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-left:auto">{section_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Final verdict ──────────────────────────────────────────────────────────────

def _render_final_verdict(result: dict) -> None:
    section_header("Final Verdict", result.get("final_rating", "Pending"))
    verdict_card(result.get("final_rating", "Pending"), result.get("final_rationale", ""))

    if result.get("override_applied"):
        st.warning(f"**Override applied:** {result.get('override_rationale', '')}")

    weights = result.get("weights") or {}
    if weights:
        w_labels = {"learning": "Learning", "practice": "Practice",
                    "exit_ticket": "Exit Ticket", "classroom": "Classroom"}
        wcols = st.columns(4)
        for col, (k, lbl) in zip(wcols, w_labels.items()):
            col.metric(lbl, f"{weights.get(k, 0)}%")

    recs = result.get("actionable_recommendations", [])
    if recs:
        st.markdown("**Actionable Recommendations:**")
        for rec in recs:
            st.markdown(f"- {rec}")


# ── Reported errors (from the 'Errors Reported' sheet tab) ──────────────────────

def _render_error_reports(errors: list) -> None:
    """Clearly-marked panel of concrete, teacher-flagged item errors."""
    if not errors:
        return
    rows = ""
    for e in errors:
        ref   = (e.get("item_ref") or e.get("activity_ref") or "").strip()
        num   = str(e.get("item_number", "") or "").strip()
        etype = (e.get("error_type", "") or "").strip()
        det   = (e.get("error_details", "") or "").strip()
        who   = (e.get("reviewer_name", "") or "").strip()
        head  = ref + (f"  ·  #{num}" if num else "")
        type_pill = (
            f'<span style="background:#FEE2E2;color:#9B1C1C;border:1px solid #F4B4B4;'
            f'padding:1px 8px;border-radius:20px;font-size:0.68rem;font-weight:700;'
            f'white-space:nowrap">{etype}</span>' if etype else ""
        )
        who_span = (f'<span style="font-size:0.68rem;color:{_MUTED}">— {who}</span>'
                    if who else "")
        rows += (
            f'<div style="border-left:3px solid {_RED};background:#FEF2F2;'
            f'border-radius:0 8px 8px 0;padding:8px 12px;margin-bottom:6px">'
            f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:2px">'
            f'<span style="font-size:0.8rem;font-weight:700;color:{_NAVY}">{head}</span>'
            f'{type_pill}{who_span}</div>'
            f'<div style="font-size:0.82rem;color:{_NAVY};line-height:1.5">{det}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="font-size:0.72rem;font-weight:800;color:{_RED};text-transform:uppercase;'
        f'letter-spacing:0.07em;margin:6px 0 8px">⚠ Reported Errors ({len(errors)})</div>'
        + rows,
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


def _ensure_ai_review(result: dict) -> dict:
    """Generate the AI expert review on demand and cache it on the result.

    Called the first time a Complete lesson's AI tab is opened, so the bulk
    refresh doesn't pay for ~10-25s LLM calls across every lesson.
    """
    from processing.ai_expert_review import generate_ai_expert_review
    from data.ai_review_reader import fetch_ai_reviews
    from utils.cache import store_result

    try:
        ai_doc_reviews = fetch_ai_reviews()
    except Exception:
        ai_doc_reviews = {}

    review = generate_ai_expert_review(
        result, result.get("flow_a_results", []), ai_doc_reviews
    )
    result["ai_expert_review"] = review
    # Persist so subsequent opens / refreshes are instant.
    try:
        store_result(result.get("activity_ref", ""), result)
    except Exception:
        pass
    return review


# ── Main entry point ───────────────────────────────────────────────────────────

def render_detail_view(result: dict) -> None:
    activity_ref = result.get("activity_ref", "")
    grade        = result.get("grade", "")
    chapter      = result.get("chapter", "")
    lesson       = result.get("lesson", "") or activity_ref
    status       = result.get("status", "Complete")
    final_rating = result.get("final_rating", "Pending")

    # Back nav + breadcrumb
    _render_back_nav(lesson)

    # ── Lesson header ─────────────────────────────────────────────────────────
    h_c1, h_c2, h_c3, h_c4, h_c5 = st.columns(5)
    h_c1.metric("Activity Ref", activity_ref or "—")
    h_c2.metric("Grade", grade or "—")
    h_c3.metric("Chapter", (chapter or "—")[:30])
    h_c4.metric("Lesson", (lesson or "—")[:30])
    h_c5.metric(
        "Final Rating",
        _RAG_DOT.get(final_rating, "•") + " " + final_rating,
    )

    if status == "Pending":
        reviews_received = len([n for n in result.get("teacher_names", []) if n])
        pending_banner(reviews_received)
        # Reported errors are still worth showing on a not-yet-complete lesson.
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        _render_error_reports(result.get("error_reports") or [])
        return

    if result.get("error"):
        error_banner(result["error"])

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Section tabs ──────────────────────────────────────────────────────────
    tab_learn, tab_practice, tab_exit, tab_ai = st.tabs([
        "📖  Learning Section",
        "✏️  Practice Section",
        "🎯  Exit Section",
        "🤖  AI Expert Review",
    ])

    per_teacher = result.get("_per_teacher_data", []) or []
    sr          = result.get("section_ratings", {}) or {}
    flow_a      = result.get("flow_a_results", []) or []

    # Load AI reviews (cached by @st.cache_data — no file read on repeat renders)
    ai_reviews = _load_ai_reviews()

    with tab_learn:
        _render_learning_section(
            flow_a, per_teacher,
            sr.get("learning", {}),
            activity_ref, ai_reviews,
        )

    with tab_practice:
        _render_practice_section(per_teacher, sr.get("practice", {}))

    with tab_exit:
        _render_exit_section(per_teacher, sr.get("exit_ticket", {}))

    with tab_ai:
        # Overall rating, section breakdown and final verdict live ONLY here —
        # the other section tabs show just their own content.
        _render_lesson_rating_bar(result)
        _render_error_reports(result.get("error_reports") or [])
        # AI review is generated lazily on first open (keeps refresh fast).
        ai_review = result.get("ai_expert_review")
        if not ai_review and result.get("_per_teacher_data"):
            with st.spinner("Generating expert review from teacher feedback…"):
                ai_review = _ensure_ai_review(result)
        _render_ai_expert_review_tab(ai_review or {})
        if status != "Pending":
            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
            _render_final_verdict(result)
