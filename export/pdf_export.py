"""PDF export with date range + filter support (Spec §12)."""
from __future__ import annotations

from datetime import datetime, date
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

RAG_COLORS_RGB = {
    "Good": colors.HexColor("#22c55e"),
    "Average": colors.HexColor("#f59e0b"),
    "Bad": colors.HexColor("#ef4444"),
    "Pending": colors.HexColor("#94a3b8"),
    "N/A": colors.HexColor("#cbd5e1"),
}


def _rag_color(rag: str):
    return RAG_COLORS_RGB.get(rag, colors.grey)


def _parse_date(val) -> Optional[date]:
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(val), fmt).date()
        except ValueError:
            continue
    return None


def _generate_teacher_summary_pdf(
    filtered: dict,
    teacher_name: str,
    from_date: Optional[date],
    to_date: Optional[date],
) -> bytes:
    """Generate a teacher-centric summary PDF showing one teacher's reviews."""
    buf  = BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=1.5*cm, rightMargin=1.5*cm,
                              topMargin=2*cm, bottomMargin=2*cm)
    styles    = getSampleStyleSheet()
    title_sty = ParagraphStyle("T", parent=styles["Title"],  fontSize=16, spaceAfter=4)
    h2_sty    = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=11, spaceAfter=3)
    body_sty  = ParagraphStyle("B", parent=styles["Normal"], fontSize=9, leading=13)
    cap_sty   = ParagraphStyle("C", parent=styles["Normal"], fontSize=8,
                                textColor=colors.HexColor("#64748b"))

    story = []
    story.append(Paragraph(f"Teacher Review Summary: {teacher_name}", title_sty))
    date_str = f"{from_date or 'All'} → {to_date or 'All'}"
    story.append(Paragraph(f"Date range: {date_str}", cap_sty))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", cap_sty))
    story.append(Spacer(1, 0.4*cm))

    if not filtered:
        story.append(Paragraph("No lessons found matching these filters.", body_sty))
        doc.build(story)
        return buf.getvalue()

    story.append(Paragraph(f"{len(filtered)} lesson(s) reviewed", h2_sty))

    table_data = [["Grade", "Chapter / Lesson", "Final RAG", "Avg Rating",
                   "Learning", "Practice", "Exit", "Notes"]]
    for ref, res in filtered.items():
        sr = res.get("section_ratings") or {}
        per_t = res.get("_per_teacher_data") or []
        teacher_notes = ""
        for row in per_t:
            n = (row.get("reviewer_name") or "").lower()
            if teacher_name.lower() in n:
                teacher_notes = (row.get("additional_suggestions") or "")[:80]
                break
        table_data.append([
            res.get("grade", ""),
            f"{res.get('chapter','')} / {res.get('lesson','')}",
            res.get("final_rating", "Pending"),
            f"{res.get('avg_teacher_rating', 0):.1f}",
            (sr.get("learning")    or {}).get("rating", "—"),
            (sr.get("practice")    or {}).get("rating", "—"),
            (sr.get("exit_ticket") or {}).get("rating", "—"),
            teacher_notes,
        ])

    col_widths = [1.2*cm, 5*cm, 1.8*cm, 1.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 3.5*cm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7.5),
        ("GRID",       (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(tbl)
    doc.build(story)
    return buf.getvalue()


def generate_pdf(
    all_results: dict,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    grade_filter: Optional[str] = None,
    chapter_filter: Optional[str] = None,
    teacher_filter: Optional[str] = None,
    rag_filter: Optional[str] = None,
    include_detail_pages: bool = False,
    teacher_summary_mode: bool = False,
) -> bytes:
    """Generate a PDF report and return as bytes."""

    # ── Filter results ────────────────────────────────────────────────────────
    filtered = {}
    for ref, res in all_results.items():
        review_date = _parse_date(res.get("review_date"))
        if from_date and review_date and review_date < from_date:
            continue
        if to_date and review_date and review_date > to_date:
            continue
        if grade_filter and grade_filter != "All" and res.get("grade") != grade_filter:
            continue
        if chapter_filter and chapter_filter != "All" and res.get("chapter") != chapter_filter:
            continue
        if teacher_filter and teacher_filter != "All":
            names = [n.lower() for n in (res.get("teacher_names") or []) if n]
            if teacher_filter.lower() not in names:
                continue
        if rag_filter and rag_filter != "All" and res.get("final_rating") != rag_filter:
            continue
        filtered[ref] = res

    if teacher_summary_mode and teacher_filter and teacher_filter != "All":
        return _generate_teacher_summary_pdf(filtered, teacher_filter, from_date, to_date)

    # ── PDF setup ─────────────────────────────────────────────────────────────
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, spaceAfter=6)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceAfter=4)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=13)
    caption_style = ParagraphStyle("Caption", parent=styles["Normal"], fontSize=8,
                                   textColor=colors.HexColor("#64748b"))

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("Cuemath Curriculum Efficacy Report", title_style))
    date_range_str = ""
    if from_date or to_date:
        date_range_str = f"{from_date or 'All'} → {to_date or 'All'}"
    story.append(Paragraph(f"Date Range: {date_range_str or 'All dates'}", caption_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", caption_style))
    story.append(Spacer(1, 0.4 * cm))

    # ── Summary stats ─────────────────────────────────────────────────────────
    total = len(filtered)
    good = sum(1 for r in filtered.values() if r.get("final_rating") == "Good")
    avg = sum(1 for r in filtered.values() if r.get("final_rating") == "Average")
    bad = sum(1 for r in filtered.values() if r.get("final_rating") == "Bad")
    pending = sum(1 for r in filtered.values() if r.get("status") == "Pending")

    stats_data = [
        ["Total Lessons", "Good 🟢", "Average 🟡", "Bad 🔴", "Pending ⏳"],
        [str(total), str(good), str(avg), str(bad), str(pending)],
    ]
    stats_table = Table(stats_data, colWidths=[3.5 * cm] * 5)
    stats_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(stats_table)
    story.append(Spacer(1, 0.5 * cm))

    # ── Master table ──────────────────────────────────────────────────────────
    story.append(Paragraph("Lesson Summary", h2_style))
    table_data = [[
        "Activity Ref", "Grade", "Chapter / Lesson",
        "Avg Teacher", "Learning", "Practice", "Exit Ticket", "Final RAG", "Summary",
    ]]
    for ref, res in filtered.items():
        sr = res.get("section_ratings", {})
        row = [
            ref,
            res.get("grade", ""),
            f"{res.get('chapter','')} / {res.get('lesson','')}",
            f"{res.get('avg_teacher_rating', 0):.1f}",
            sr.get("learning", {}).get("rating", "—") if sr else "—",
            sr.get("practice", {}).get("rating", "—") if sr else "—",
            sr.get("exit_ticket", {}).get("rating", "—") if sr else "—",
            res.get("final_rating", "Pending"),
            (res.get("one_line_summary", ""))[:80],
        ]
        table_data.append(row)

    col_widths = [2.8*cm, 1.2*cm, 4.5*cm, 1.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm, 4*cm]
    master_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    rag_col_idx = 7
    ts_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]
    # Colour RAG cells
    for i, row_data in enumerate(table_data[1:], start=1):
        for col_idx in [4, 5, 6, rag_col_idx]:
            val = row_data[col_idx]
            c = _rag_color(val)
            ts_cmds.append(("BACKGROUND", (col_idx, i), (col_idx, i), c))
            ts_cmds.append(("TEXTCOLOR", (col_idx, i), (col_idx, i), colors.white))

    master_table.setStyle(TableStyle(ts_cmds))
    story.append(master_table)

    # ── Optional detail pages ──────────────────────────────────────────────────
    if include_detail_pages:
        for ref, res in filtered.items():
            story.append(PageBreak())
            story.append(Paragraph(f"Lesson Detail: {ref}", h2_style))
            story.append(Paragraph(
                f"Grade: {res.get('grade','')} | Chapter: {res.get('chapter','')} | "
                f"Lesson: {res.get('lesson','')}",
                caption_style,
            ))
            story.append(Spacer(1, 0.3 * cm))

            final = res.get("final_rating", "Pending")
            story.append(Paragraph(f"Final Rating: <b>{final}</b>", body_style))
            story.append(Paragraph(res.get("final_rationale", ""), body_style))
            story.append(Spacer(1, 0.2 * cm))

            recs = res.get("actionable_recommendations", [])
            if recs:
                story.append(Paragraph("Recommendations:", h2_style))
                for rec in recs:
                    story.append(Paragraph(f"• {rec}", body_style))

            flow_a = res.get("flow_a_results", [])
            if flow_a:
                story.append(Spacer(1, 0.3 * cm))
                story.append(Paragraph("Learning Items:", h2_style))
                for item in flow_a:
                    story.append(Paragraph(
                        f"<b>{item.get('item_ref','?')}</b>: {item.get('rating','?')} — "
                        f"{item.get('rationale','')[:200]}",
                        body_style,
                    ))

    doc.build(story)
    return buf.getvalue()
