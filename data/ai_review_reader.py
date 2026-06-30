"""AI Review Reader — fetches expert item reviews from the consolidated Google Doc.

The document maps Widget IDs (= activity_ref / item_ref) to structured review
feedback written by an AI/curriculum expert. Currently holds ~4 items; will grow
to 10+.
"""
from __future__ import annotations

import json
import re
import time

import requests

from config.settings import CACHE_DIR, AI_REVIEW_EXPORT_URL

_CACHE_FILE = CACHE_DIR / "ai_reviews.json"
_CACHE_TTL  = 3600  # 1 hour


# ── Fetch ──────────────────────────────────────────────────────────────────────

def _fetch_doc_text() -> str:
    try:
        resp = requests.get(
            AI_REVIEW_EXPORT_URL,
            timeout=20,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        print(f"[ai_review] Fetch failed: {exc}")
        return ""


# ── Parse ──────────────────────────────────────────────────────────────────────

_WIDGET_ID_RE = re.compile(
    r"^[A-Z]{2}-G[0-9K]+-",   # starts with country code + grade prefix e.g. "US-G3-"
    re.IGNORECASE,
)


def _looks_like_widget_id(line: str) -> bool:
    return bool(_WIDGET_ID_RE.match(line))


def _extract_grade(widget_id: str) -> str:
    """Extract grade from widget ID like 'US-G4-...' → '4'."""
    m = re.search(r"-G([0-9K]+)-", widget_id, re.IGNORECASE)
    return m.group(1) if m else ""


def _commit(current: dict, feedback: list, reviews: dict) -> None:
    wid = current.get("widget_id", "").strip()
    if wid and feedback:
        current = dict(current)
        current["feedback"] = list(feedback)
        reviews[wid] = current


def _parse_reviews(text: str) -> dict:
    """Parse plain-text Google Doc export → {widget_id: review_dict}.

    Actual doc format (from text export):
      Grade [N]           ← grade header line (may just say "Grade" for first item)
      <subject>           ← e.g. "Measurement of Mass"
      <topic>             ← e.g. "Compare and Order Objects"
      <widget_id>         ← e.g. "US-G3-Compare-...-V3-1.W05"
      <blank lines>
      <feedback prose>    ← paragraph text, not bullet points
    """
    reviews: dict  = {}
    current: dict  = {}
    feedback: list = []

    # Keep a small context window of recent non-empty lines to capture
    # subject/topic lines that appear just before the widget ID.
    recent: list[str] = []

    lines = text.splitlines()

    for raw in lines:
        line = raw.strip().lstrip("﻿")  # strip BOM from first line too
        if not line:
            continue

        if _looks_like_widget_id(line):
            # Save previous block
            _commit(current, feedback, reviews)

            # recent[-3], [-2], [-1] are typically: grade, subject, topic
            grade   = ""
            subject = ""
            topic   = ""
            if len(recent) >= 3:
                grade_line = recent[-3]
                gm = re.match(r"Grade\s*([0-9K]*)", grade_line, re.IGNORECASE)
                if gm:
                    grade = gm.group(1).strip() or _extract_grade(line)
                subject = recent[-2]
                topic   = recent[-1]
            elif len(recent) == 2:
                subject = recent[-2]
                topic   = recent[-1]
                grade   = _extract_grade(line)
            elif len(recent) == 1:
                subject = recent[-1]
                grade   = _extract_grade(line)
            else:
                grade = _extract_grade(line)

            current  = {"grade": grade, "subject": subject, "topic": topic, "widget_id": line}
            feedback = []
            recent   = []
            continue

        # Accumulate recent non-empty lines (used as context before widget ID)
        recent.append(line)
        if len(recent) > 4:
            recent.pop(0)

        # If we're inside a widget block, collect feedback lines
        if current.get("widget_id"):
            # Skip lines that look like grade/subject/topic of the NEXT item
            # (they'll be captured by recent[] when the next widget ID appears)
            feedback.append(line)

    _commit(current, feedback, reviews)

    # Post-process: trim feedback to remove lines that are actually metadata
    # for the next item (grade / subject / topic appearing at the tail).
    for wid, rev in list(reviews.items()):
        fb = rev.get("feedback", [])
        # Drop trailing lines that look like grade labels or short category headers
        while fb and (
            re.match(r"^Grade\s*\d*$", fb[-1], re.IGNORECASE)
            or len(fb[-1]) < 4
        ):
            fb.pop()
        rev["feedback"] = fb

    return reviews


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_ai_reviews(force: bool = False) -> dict:
    """Return {widget_id: review_dict}. Cached for 1 hour."""
    if not force and _CACHE_FILE.exists():
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - data.get("_cached_at", 0) < _CACHE_TTL:
                return data.get("reviews", {})
        except Exception:
            pass

    text    = _fetch_doc_text()
    reviews = _parse_reviews(text) if text else {}

    try:
        _CACHE_FILE.write_text(
            json.dumps({"_cached_at": time.time(), "reviews": reviews}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass

    return reviews


def get_item_review(item_ref: str, all_reviews: dict | None = None) -> dict:
    """Return the AI review for item_ref, or {} if not found."""
    if all_reviews is None:
        all_reviews = fetch_ai_reviews()
    if not all_reviews:
        return {}

    # Exact match
    if item_ref in all_reviews:
        return all_reviews[item_ref]

    # Partial / case-insensitive match (handles minor formatting differences)
    item_lower = item_ref.lower()
    for wid, review in all_reviews.items():
        if item_lower in wid.lower() or wid.lower() in item_lower:
            return review

    return {}
