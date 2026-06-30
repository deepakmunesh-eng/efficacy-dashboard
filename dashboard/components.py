"""Shared UI components — Cuemath design system."""
import streamlit as st

# ── Design tokens (keep in sync with theme.py) ─────────────────────────────
_NAVY   = "#0E1B3D"
_GREEN  = "#2DBD6E"
_AMBER  = "#F59E0B"
_RED    = "#E84C3D"
_MUTED  = "#5B6B82"
_BORDER = "#E4EAF3"
_SURFACE = "#FFFFFF"
_GROUND = "#F4F6FF"

# Text/bg pairs per RAG state
RAG_COLORS = {
    "Good":    _GREEN,
    "Average": _AMBER,
    "Bad":     _RED,
    "Pending": "#94A3B8",
    "N/A":     "#CBD5E1",
}
RAG_BG = {
    "Good":    "#EDFAF3",
    "Average": "#FFF8EB",
    "Bad":     "#FEF1F1",
    "Pending": "#F8FAFC",
    "N/A":     "#F8FAFC",
}
RAG_TEXT = {
    "Good":    "#156D3E",
    "Average": "#8A5800",
    "Bad":     "#9B1C1C",
    "Pending": "#475569",
    "N/A":     "#64748B",
}


def rag_badge(rag: str, size: str = "normal") -> str:
    """Colored dot + tinted pill — reads clearly in tables and in cards."""
    color  = RAG_COLORS.get(rag, "#94A3B8")
    bg     = RAG_BG.get(rag, "#F8FAFC")
    text   = RAG_TEXT.get(rag, "#475569")
    fs     = "0.72rem" if size == "small" else "0.82rem"
    dot_sz = "6px" if size == "small" else "7px"
    return (
        f'<span style="'
        f'display:inline-flex;align-items:center;gap:5px;'
        f'background:{bg};color:{text};'
        f'padding:4px 10px 4px 8px;'
        f'border-radius:20px;'
        f'font-size:{fs};font-weight:700;'
        f'letter-spacing:0.04em;'
        f'border:1px solid {color}33;'
        f'">'
        f'<span style="width:{dot_sz};height:{dot_sz};border-radius:50%;'
        f'background:{color};flex-shrink:0"></span>'
        f'{rag}'
        f'</span>'
    )


def section_header(title: str, rag: str | None = None) -> None:
    """Section heading: 3px green accent bar + navy title + optional RAG badge."""
    badge = f"&ensp;{rag_badge(rag)}" if rag else ""
    st.markdown(
        f"""
        <div style="margin:1.5rem 0 1rem">
          <div style="width:24px;height:3px;background:{_GREEN};border-radius:2px;margin-bottom:7px"></div>
          <h3 style="
            font-family:'Plus Jakarta Sans',sans-serif;
            font-size:1.05rem;font-weight:700;color:{_NAVY};
            margin:0;line-height:1.3;
            display:flex;align-items:center;flex-wrap:wrap;gap:6px;
          ">{title}{badge}</h3>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, color: str = _GREEN) -> None:
    """Clean white metric card with a coloured top border."""
    st.markdown(
        f"""
        <div style="
          background:{_SURFACE};border-radius:12px;
          padding:1rem 1.25rem;
          border:1px solid {_BORDER};border-top:3px solid {color};
          box-shadow:0 1px 4px rgba(14,27,61,0.05);
          margin-bottom:8px;
        ">
          <div style="
            font-size:0.68rem;font-weight:700;
            color:{_MUTED};text-transform:uppercase;letter-spacing:0.08em;
            margin-bottom:6px;
          ">{label}</div>
          <div style="
            font-family:'Plus Jakarta Sans',sans-serif;
            font-size:1.4rem;font-weight:800;color:{_NAVY};
          ">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def teacher_card(name: str, rating: float, summary_dict: dict) -> None:
    """Teacher review card with coloured top border matching rating."""
    if rating >= 4.0:
        rc = _GREEN
    elif rating >= 2.5:
        rc = _AMBER
    else:
        rc = _RED

    st.markdown(
        f"""
        <div style="
          background:{_SURFACE};border-radius:12px;
          padding:1.25rem;
          border:1px solid {_BORDER};border-top:3px solid {rc};
          box-shadow:0 1px 4px rgba(14,27,61,0.05);
        ">
          <div style="
            font-family:'Plus Jakarta Sans',sans-serif;
            font-weight:700;font-size:0.9rem;color:{_NAVY};
            margin-bottom:4px;
          ">{name}</div>
          <div style="
            font-size:1.45rem;font-weight:800;color:{rc};
            margin-bottom:8px;line-height:1;
          ">{rating:.1f}<span style="font-size:0.9rem;font-weight:500;color:{_MUTED}">/5</span></div>
        """,
        unsafe_allow_html=True,
    )
    for key, val in summary_dict.items():
        if val:
            st.markdown(f"**{key}:** {val}")
    st.markdown("</div>", unsafe_allow_html=True)


def divergence_warning(divergences: list[dict]) -> None:
    if not divergences:
        return
    st.markdown(
        f"""
        <div style="
          background:#FFFBEB;
          border-left:4px solid {_AMBER};
          border-radius:0 10px 10px 0;
          padding:10px 14px;margin:8px 0;
        ">
          <span style="font-weight:700;color:#92400E">
            ⚡ {len(divergences)} teacher divergence(s) detected
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for d in divergences:
        st.markdown(
            f"- **{d.get('dimension', 'Dimension')}:** {d.get('description', '')} "
            f"— _{d.get('teacher_positions', '')}_"
        )


def pending_banner(reviews_received: int) -> None:
    st.markdown(
        f"""
        <div style="
          background:#FFFBEB;
          border-left:4px solid {_AMBER};
          border-radius:0 10px 10px 0;
          padding:12px 16px;margin:8px 0;
        ">
          <span style="font-weight:700;color:#92400E">⏳ Pending</span>
          <span style="color:#78350F"> — {reviews_received}/3 teacher reviews received.
          Full analysis runs once all 3 are complete.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def error_banner(msg: str) -> None:
    st.markdown(
        f"""
        <div style="
          background:#FEF1F1;
          border-left:4px solid {_RED};
          border-radius:0 10px 10px 0;
          padding:12px 16px;margin:8px 0;
        ">
          <span style="font-weight:700;color:#9B1C1C">Error</span>
          <span style="color:#7F1D1D"> — {msg}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def verdict_card(final_rating: str, rationale: str) -> None:
    """Large final verdict display."""
    color  = RAG_COLORS.get(final_rating, "#94A3B8")
    bg     = RAG_BG.get(final_rating, "#F8FAFC")
    text   = RAG_TEXT.get(final_rating, "#475569")
    st.markdown(
        f"""
        <div style="
          background:{bg};
          border:1.5px solid {color}55;
          border-left:5px solid {color};
          border-radius:0 14px 14px 0;
          padding:1.25rem 1.5rem;margin:0.5rem 0;
        ">
          <div style="
            font-family:'Plus Jakarta Sans',sans-serif;
            font-size:1.8rem;font-weight:800;
            color:{text};line-height:1;margin-bottom:8px;
            display:flex;align-items:center;gap:10px;
          ">
            <span style="
              width:12px;height:12px;border-radius:50%;
              background:{color};display:inline-block;flex-shrink:0;
            "></span>
            {final_rating}
          </div>
          <div style="color:{_NAVY};font-size:0.92rem;line-height:1.55;">{rationale}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
