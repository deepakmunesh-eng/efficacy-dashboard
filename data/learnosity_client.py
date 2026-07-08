"""
Lesson content fetcher — pulls from Michelangelo Studio (Supabase).

The `lessons` table has a `learnosity_activity_reference` field that matches
Column B (Activity Reference) in the teacher review sheet exactly.

The `objective` field contains a rich structured description of the lesson:
concepts, practice structure, exit ticket, grade level, character names, etc.
This is used by the scoring engine for context-aware analysis.

All fetched content is cached in .cache/learnosity_content.json.
"""
from __future__ import annotations

import json
import time

import requests

from config.settings import (
    SUPABASE_LESSONS_ENDPOINT, SUPABASE_ANON_KEY, RAILWAY_BACKEND_URL, CACHE_DIR,
)
from utils.cache import get_learnosity_content, store_learnosity_content

_RAILWAY_ITEMS_CACHE = CACHE_DIR / "railway_items.json"

_HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
}


def _fetch_from_supabase(activity_ref: str) -> dict | None:
    """
    Query the lessons table by learnosity_activity_reference.
    Returns the first matching lesson record as a content dict.
    """
    try:
        # Single OR query across the three ref columns — was 3 sequential requests
        # per lesson (worksheet, then target-practice, then smart-practice).
        or_filter = (
            f'(learnosity_activity_reference.eq."{activity_ref}",'
            f'learnosity_tp_activity_reference.eq."{activity_ref}",'
            f'learnosity_sp_activity_reference.eq."{activity_ref}")'
        )
        resp = requests.get(
            SUPABASE_LESSONS_ENDPOINT,
            headers=_HEADERS,
            params={"select": "*", "or": or_filter, "limit": 1},
            timeout=12,
        )
        resp.raise_for_status()
        records = resp.json()

        if not records:
            return None

        lesson = records[0]
        return {
            "activity_ref":   activity_ref,
            "source":         "michelangelo_studio",
            "lesson_id":      lesson.get("id"),
            "lesson_name":    lesson.get("name", ""),
            "objective":      lesson.get("objective", ""),
            "chapter_id":     lesson.get("chapter_id"),
            "position":       lesson.get("position"),
            "minigoals":      lesson.get("minigoals", ""),
            "learnosity_refs": {
                "worksheet":       lesson.get("learnosity_activity_reference", ""),
                "target_practice": lesson.get("learnosity_tp_activity_reference", ""),
                "smart_practice":  lesson.get("learnosity_sp_activity_reference", ""),
                "advanced":        lesson.get("learnosity_adv_activity_reference", ""),
            },
            "setup_flags": {
                "setup_done":           lesson.get("setup_done", False),
                "microgoals_done":      lesson.get("microgoals_setup_done", False),
                "target_practice_done": lesson.get("target_practice_setup_done", False),
                "smart_practice_done":  lesson.get("smart_practice_setup_done", False),
                "advanced_done":        lesson.get("advanced_content_setup_done", False),
                "pdf_done":             lesson.get("pdf_setup_done", False),
            },
        }

    except Exception as exc:
        print(f"[learnosity] Supabase fetch failed for '{activity_ref}': {exc}")
        return None


def _fallback(activity_ref: str) -> dict:
    return {
        "activity_ref": activity_ref,
        "source":       "unavailable",
        "lesson_name":  "",
        "objective":    "",
        "note":         "Lesson not found in Michelangelo Studio. Analysis based on teacher feedback only.",
    }


# ── Public interface ──────────────────────────────────────────────────────────

def get_lesson_content(activity_ref: str, force_refresh: bool = False) -> dict:
    """Return lesson content for an activity_ref. Uses cache unless force_refresh."""
    if not force_refresh:
        cached = get_learnosity_content(activity_ref)
        if cached and cached.get("source") != "unavailable":
            return cached

    content = _fetch_from_supabase(activity_ref) or _fallback(activity_ref)
    store_learnosity_content(activity_ref, content)
    return content


def fetch_activity_items(activity_ref: str, auth_token: str) -> list[str]:
    """Return a list of item reference strings for an activity.

    Calls the Railway backend API (requires user JWT).  Results are cached
    locally for 1 hour.  Returns [] on auth failure or network error.
    """
    if not auth_token:
        return []

    # Check local cache first
    try:
        if _RAILWAY_ITEMS_CACHE.exists():
            cached = json.loads(_RAILWAY_ITEMS_CACHE.read_text(encoding="utf-8"))
            entry = cached.get(activity_ref, {})
            if entry and time.time() - entry.get("_ts", 0) < 3600:
                return entry.get("refs", [])
    except Exception:
        pass

    try:
        resp = requests.get(
            f"{RAILWAY_BACKEND_URL}/api/learnosity/items",
            params={"activity_reference": activity_ref},
            headers={"Authorization": f"Bearer {auth_token}"},
            timeout=20,
        )
        if resp.status_code in (401, 403):
            print(f"[railway] Auth rejected for '{activity_ref}' (HTTP {resp.status_code})")
            return []
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[railway] Item fetch failed for '{activity_ref}': {exc}")
        return []

    # Normalise various response shapes → list of ref strings
    refs: list[str] = []
    raw_items: list = []
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = data.get("items") or data.get("data") or []

    for item in raw_items:
        if isinstance(item, str):
            refs.append(item)
        elif isinstance(item, dict):
            ref = (item.get("reference") or item.get("item_reference")
                   or item.get("ref") or item.get("id") or "")
            if ref:
                refs.append(str(ref))

    # Persist to cache
    try:
        cache: dict = {}
        if _RAILWAY_ITEMS_CACHE.exists():
            cache = json.loads(_RAILWAY_ITEMS_CACHE.read_text(encoding="utf-8"))
        cache[activity_ref] = {"refs": refs, "_ts": time.time()}
        _RAILWAY_ITEMS_CACHE.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass

    return refs


def format_content_for_prompt(content: dict) -> str:
    """Render lesson content as readable text for scoring context."""
    if content.get("source") == "unavailable":
        return content.get("note", "Content unavailable.")

    lines = [
        f"Lesson: {content.get('lesson_name', '')}",
        f"Activity Reference: {content.get('activity_ref', '')}",
        f"Minigoal: {content.get('minigoals', '')}",
        "",
        "=== LESSON OBJECTIVE & STRUCTURE ===",
        content.get("objective", "No objective available."),
    ]

    refs = content.get("learnosity_refs", {})
    if any(refs.values()):
        lines += [
            "",
            "=== LEARNOSITY REFERENCES ===",
            f"Worksheet:       {refs.get('worksheet', '')}",
            f"Target Practice: {refs.get('target_practice', '')}",
            f"Smart Practice:  {refs.get('smart_practice', '')}",
        ]
        if refs.get("advanced"):
            lines.append(f"Advanced:        {refs['advanced']}")

    return "\n".join(lines)
