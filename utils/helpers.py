import re
from datetime import datetime
from typing import Any


def normalize_name(name: str) -> str:
    """Strip spaces, lowercase — used for teacher deduplication."""
    return re.sub(r"\s+", "", name or "").lower()


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def rating_to_rag(score: float) -> str:
    """Convert numeric score to Good/Average/Bad."""
    if score >= 4.0:
        return "Good"
    if score >= 2.5:
        return "Average"
    return "Bad"


def rag_badge_html(rag: str) -> str:
    colors = {"Good": "#22c55e", "Average": "#f59e0b", "Bad": "#ef4444", "Pending": "#94a3b8", "N/A": "#cbd5e1"}
    color = colors.get(rag, "#94a3b8")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:0.8rem;font-weight:600">{rag}</span>'
    )


def parse_date(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            continue
    return None


def truncate(text: str, max_chars: int = 120) -> str:
    if not text:
        return ""
    text = text.strip()
    return text[:max_chars] + "…" if len(text) > max_chars else text
