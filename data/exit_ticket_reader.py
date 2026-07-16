"""
Exit-ticket student-performance data.

Source: the "summary" tab of the exit-ticket Google Sheet — one row per widget
with `learnosity_activity_ref`, `item_ref`, `avg-score`, `max-score`.

Scoring (per the curriculum team):
  per widget  → (avg-score / max-score) * 100
  per item    → mean of its widgets' percentages
  per lesson  → mean of its items' percentages  (the activity's exit %)
  health 1-5  → percentage * 5 / 100  (linear; 100% → 5.0)

Lessons are keyed by `learnosity_activity_ref`, which matches the review sheet's
Activity Reference ID directly (verified for 236 lessons incl. the G4 pilot).
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import requests

from config.settings import EXIT_TICKET_XLSX_URL

_SUMMARY_TAB = "summary"      # one row per widget: avg-score / max-score
_RAW_TAB     = "ET-data-raw"  # one row per student attempt (for student counts)
# header text (lowercased/stripped) → field
_COLS = {
    "learnosity_activity_ref": "activity_ref",
    "item_ref":                "item_ref",
    "widget_ref":              "widget_ref",
    "avg-score":               "avg_score",
    "max-score":               "max_score",
}


def _students_by_activity(xl) -> dict:
    """Approx. students who attempted each activity's exit ticket = the max number
    of attempt rows on any single widget of that activity (every student attempts
    the first widget; later widgets may have fewer)."""
    try:
        df = xl.parse(_RAW_TAB, header=0, dtype=str)
    except Exception:  # noqa: BLE001
        return {}
    cols = {str(c).strip().lower(): c for c in df.columns}
    ac = cols.get("learnosity_activity_ref"); wc = cols.get("widget_ref")
    if not ac or not wc:
        return {}
    from collections import Counter, defaultdict
    per_widget: dict = defaultdict(Counter)     # activity -> Counter(widget -> rows)
    for act, wid in zip(df[ac].astype(str), df[wc].astype(str)):
        act = act.strip()
        if act:
            per_widget[act][wid.strip()] += 1
    return {act: (max(c.values()) if c else 0) for act, c in per_widget.items()}


def _to_float(x):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def fetch_exit_ticket_scores() -> dict[str, dict]:
    """Return {activity_ref: {"pct": 0-100, "score_5": 1-5, "n_items", "n_widgets"}}.
    Empty dict on any failure (exit component then simply redistributes)."""
    try:
        resp = requests.get(EXIT_TICKET_XLSX_URL, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        xl = pd.ExcelFile(BytesIO(resp.content), engine="openpyxl")
        if _SUMMARY_TAB not in xl.sheet_names:
            print(f"[exit_ticket_reader] '{_SUMMARY_TAB}' tab not found")
            return {}
        df = xl.parse(_SUMMARY_TAB, header=0, dtype=str)
        students = _students_by_activity(xl)
    except Exception as exc:  # noqa: BLE001
        print(f"[exit_ticket_reader] fetch failed: {exc}")
        return {}

    # Map columns by header text (case-insensitive).
    colmap = {}
    for c in df.columns:
        key = str(c).strip().lower()
        if key in _COLS:
            colmap[c] = _COLS[key]
    df = df.rename(columns=colmap)
    if not {"activity_ref", "item_ref", "avg_score", "max_score"} <= set(df.columns):
        print(f"[exit_ticket_reader] missing expected columns; got {list(df.columns)}")
        return {}

    # widget %  →  item %  →  activity %
    #   items[activity][item] = [widget_pct, ...]
    items: dict[str, dict[str, list[float]]] = {}
    for _, row in df.iterrows():
        act = str(row.get("activity_ref", "") or "").strip()
        item = str(row.get("item_ref", "") or "").strip()
        avg = _to_float(row.get("avg_score"))
        mx = _to_float(row.get("max_score"))
        if not act or avg is None or not mx:      # skip blanks / max 0
            continue
        pct = max(0.0, min(100.0, avg / mx * 100.0))
        items.setdefault(act, {}).setdefault(item or "_", []).append(pct)

    out: dict[str, dict] = {}
    for act, by_item in items.items():
        item_pcts = [sum(ws) / len(ws) for ws in by_item.values() if ws]
        if not item_pcts:
            continue
        pct = round(sum(item_pcts) / len(item_pcts), 1)
        out[act] = {
            "pct":       pct,
            "score_5":   round(pct * 5.0 / 100.0, 2),
            "n_items":   len(by_item),
            "n_widgets": sum(len(ws) for ws in by_item.values()),
            "students":  int(students.get(act, 0)),
        }
    return out
