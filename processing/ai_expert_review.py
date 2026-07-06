"""AI Expert Review — calls Claude to synthesise Learnosity content + teacher feedback.

Inputs per lesson:
  - Learnosity item content (fetched directly via Data API using consumer key/secret)
  - 3 teacher field reviews (from Flow A/B)
  - Google Doc sample reviews (used as few-shot reference examples)

Output:
  {final_rating, overall_summary, strengths, concerns, recommendations, confidence, ...}

Requires env vars:
  LLM_GATEWAY_BASE_URL     — Cuemath LLM gateway (LiteLLM→Bedrock); defaults to https://llm-gateway.cuemath.com
  LLM_API_KEY              — virtual key for the LLM gateway
  LLM_MODEL                — optional model alias the gateway exposes (defaults to "claude-sonnet-5")
  DATA_GATEWAY_BASE_URL    — Cuemath data gateway resources endpoint (proxies to LEARNOSITY)
  DATA_GATEWAY_TOKEN       — Bearer token for the gateway
  LEARNOSITY_MS_DOMAIN_URL — optional signing domain, defaults to "leap.cuemath.com"
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request

from config.settings import (
    CACHE_DIR,
    DATA_GATEWAY_BASE_URL,
    DATA_GATEWAY_TOKEN,
    LEARNOSITY_MS_DOMAIN_URL,
    LLM_GATEWAY_BASE_URL,
    LLM_API_KEY,
    LLM_MODEL,
)

_CACHE_FILE  = CACHE_DIR / "ai_expert_reviews.json"
_CACHE_TTL   = 86400 * 7          # 7 days — re-generate when teacher reviews change


# ── Cuemath data gateway (Learnosity reads) ────────────────────────────────────
# We hold no Learnosity credentials of our own — every read goes through the
# Cuemath data gateway, which proxies to the LEARNOSITY service (learnosity-ms).
#
#   POST <DATA_GATEWAY_BASE_URL>
#     Authorization: Bearer <DATA_GATEWAY_TOKEN>
#     { service: "LEARNOSITY", path, method: "POST",
#       payload: { domain_url, <learnosity-ms view body> } }
#
# The v2 read endpoints paginate server-side and return the flat records list as
# `data`; the gateway wraps that as { data: [...] }. _gateway_post unwraps one
# level so callers get the list directly (mirrors the studio's learnosityRead()).

def _gateway_post(path: str, payload: dict):
    if not DATA_GATEWAY_BASE_URL or not DATA_GATEWAY_TOKEN:
        raise RuntimeError(
            "data gateway not configured (DATA_GATEWAY_BASE_URL / DATA_GATEWAY_TOKEN)"
        )
    body = json.dumps({
        "service": "LEARNOSITY",
        "path":    path,
        "method":  "POST",
        "payload": {"domain_url": LEARNOSITY_MS_DOMAIN_URL, **payload},
    }).encode("utf-8")
    req = urllib.request.Request(DATA_GATEWAY_BASE_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {DATA_GATEWAY_TOKEN}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=25) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if isinstance(result, dict) and "data" in result:
        return result["data"]
    return result


def _normalize_tags(raw) -> dict:
    """Coerce Learnosity tags to {Type: [str, ...]}. Values arrive as strings or
    {name}/{value} dicts depending on the endpoint."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for type_, values in raw.items():
        if not isinstance(values, list):
            continue
        names = []
        for v in values:
            if isinstance(v, str):
                names.append(v)
            elif isinstance(v, dict):
                nm = v.get("name") or v.get("value")
                if nm:
                    names.append(nm)
        if names:
            out[type_] = names
    return out


def _item_body(item: dict) -> dict:
    """Learnosity returns an item's fields at top level or nested under `.data`."""
    data = item.get("data")
    return data if isinstance(data, dict) else item


def _fetch_items_content(item_refs: list[str]) -> list[dict]:
    """Fetch full item + question content via the Cuemath data gateway.

    Returns items reshaped as
    {reference, title, tags, questions:[{reference, type, data}]} — the form
    _summarise_item expects.
    """
    if not item_refs or not (DATA_GATEWAY_BASE_URL and DATA_GATEWAY_TOKEN):
        return []
    try:
        # 1. Items (v2/items paginates internally; chunk refs defensively)
        items: list[dict] = []
        for i in range(0, len(item_refs), 50):
            chunk = item_refs[i:i + 50]
            data  = _gateway_post(
                "/learnosity/v2/items/",
                {"request_data": {"references": chunk, "limit": 50}},
            )
            if isinstance(data, list):
                items.extend(x for x in data if isinstance(x, dict))

        # 2. Collect each item's question references from its widgets
        item_qrefs: list[list[str]] = []
        all_qrefs:  list[str]       = []
        for item in items:
            defn    = _item_body(item).get("definition") or {}
            widgets = defn.get("widgets") or item.get("questions") or []
            refs    = [w.get("reference") for w in widgets
                       if isinstance(w, dict) and w.get("reference")]
            item_qrefs.append(refs)
            all_qrefs.extend(refs)

        # 3. Questions, keyed by reference
        qmap: dict = {}
        for i in range(0, len(all_qrefs), 200):
            chunk = all_qrefs[i:i + 200]
            qdata = _gateway_post(
                "/learnosity/v2/questions/",
                {"question_references": chunk},
            )
            for q in (qdata or []):
                if not isinstance(q, dict):
                    continue
                qbody = q.get("data") if isinstance(q.get("data"), dict) else q
                ref   = q.get("reference") or qbody.get("reference")
                if ref:
                    qmap[ref] = {
                        "reference": ref,
                        "type":      qbody.get("type", "") or "",
                        "data":      qbody,
                    }

        # 4. Reshape into the {reference, title, tags, questions} form
        shaped: list[dict] = []
        for item, refs in zip(items, item_qrefs):
            body = _item_body(item)
            shaped.append({
                "reference": item.get("reference", ""),
                "title":     item.get("title") or body.get("description") or "",
                "tags":      _normalize_tags(body.get("tags") or item.get("tags")),
                "questions": [qmap[r] for r in refs if r in qmap],
            })
        return shaped
    except Exception as exc:
        print(f"[ai_expert_review] Learnosity gateway fetch failed: {exc}")
        return []


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def _summarise_item(item: dict) -> dict:
    """Convert a raw Learnosity item into a compact dict for the Claude prompt."""
    questions = item.get("questions") or []
    tags      = item.get("tags") or {}
    tag_flat  = tags if isinstance(tags, dict) else {}

    item_type_tag = tag_flat.get("Item Type", [])
    item_type     = (item_type_tag[0] if isinstance(item_type_tag, list) and item_type_tag
                     else str(item_type_tag))

    lower = item_type.lower()
    if "exit" in lower:
        section = "Exit Ticket"
    elif "practice" in lower or "mini-quiz" in lower:
        section = "Practice"
    else:
        section = "Learning"

    questions_data = []
    for q in questions[:5]:
        qdata    = q.get("data", {}) if isinstance(q, dict) else {}
        stimulus = _strip_html(qdata.get("stimulus", ""))[:300]
        opts     = [_strip_html(o.get("label", "") if isinstance(o, dict) else str(o))[:80]
                    for o in (qdata.get("options") or [])[:4]]
        hint     = _strip_html(qdata.get("hint", ""))[:150]
        questions_data.append({
            "type":     q.get("type", "") if isinstance(q, dict) else "",
            "stimulus": stimulus,
            "options":  opts,
            "hint":     hint,
        })

    return {
        "reference":     item.get("reference", ""),
        "title":         item.get("title") or "",
        "section":       section,
        "item_type":     item_type,
        "question_count": len(questions),
        "questions":     questions_data,
    }


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _format_items_text(items: list[dict]) -> str:
    if not items:
        return "(Item content not available — review based on teacher feedback only)"
    lines = []
    for item in items:
        lines.append(f"\n### {item['reference']}  [{item['section']} | {item['item_type']}]")
        for q in item.get("questions", []):
            lines.append(f"  [{q['type']}] {q['stimulus']}")
            if q.get("options"):
                lines.append("  Choices: " + " / ".join(q["options"]))
            if q.get("hint"):
                lines.append(f"  Hint: {q['hint']}")
    return "\n".join(lines)


def _format_teacher_text(per_teacher: list, flow_a_results: list) -> str:
    lines = []
    for row in per_teacher:
        name = (row.get("reviewer_name") or "Teacher").strip()
        parts = [f"**{name}**"]
        if row.get("overall_rating"):
            parts.append(f"  Overall: {row['overall_rating']}/5")
        if row.get("practice_quality"):
            parts.append(f"  Practice quality: {row['practice_quality']}")
        if row.get("practice_observations"):
            parts.append(f"  Practice obs: {str(row['practice_observations'])[:180]}")
        if row.get("exit_ticket_quality"):
            parts.append(f"  Exit ticket: {row['exit_ticket_quality']}")
        if row.get("exit_ticket_observations"):
            parts.append(f"  Exit obs: {str(row['exit_ticket_observations'])[:180]}")
        if row.get("additional_suggestions"):
            parts.append(f"  Suggestions: {str(row['additional_suggestions'])[:180]}")
        lines.append("\n".join(parts))

    for item_result in flow_a_results:
        ref    = item_result.get("item_ref", "")
        rating = item_result.get("rating", "")
        score  = float(item_result.get("score") or 0)
        if ref:
            lines.append(f"\nItem {ref}: {rating} ({score:.1f}/5)")
            for t_data in (item_result.get("teacher_summaries") or {}).values():
                summ = (t_data.get("summary") or "")
                name = (t_data.get("name") or "")
                if summ and summ != "No detailed feedback provided.":
                    lines.append(f"  {name}: {summ[:150]}")
    return "\n".join(lines)


def _format_doc_samples(ai_doc_reviews: dict) -> str:
    if not ai_doc_reviews:
        return "(No reference samples available)"
    lines = []
    for wid, rev in list(ai_doc_reviews.items())[:2]:
        lines.append(f"\nSample expert review — {wid}:")
        for fb in (rev.get("feedback") or [])[:4]:
            lines.append(f"  • {fb}")
    return "\n".join(lines)


def _build_prompt(
    lesson_meta: dict,
    items_text: str,
    teacher_text: str,
    section_scores: dict,
    doc_samples: str,
) -> str:
    lr = section_scores.get("learning",    {})
    pr = section_scores.get("practice",    {})
    et = section_scores.get("exit_ticket", {})

    return f"""You are a senior Cuemath curriculum quality expert reviewing a K-8 math lesson on Learnosity.

## Lesson
Grade {lesson_meta.get('grade','')} | {lesson_meta.get('chapter','')} | {lesson_meta.get('lesson','')}
Activity ref: {lesson_meta.get('activity_ref','')}

## Learnosity Item Content
{items_text}

## Teacher Field Scores (3 teachers, rule-based)
Learning: {lr.get('score',0):.1f}/5 ({lr.get('rating','—')}) | Practice: {pr.get('score',0):.1f}/5 ({pr.get('rating','—')}) | Exit Ticket: {et.get('score',0):.1f}/5 ({et.get('rating','—')})

## Teacher Qualitative Feedback
{teacher_text}

## Expert Review Reference Examples (from curriculum doc)
{doc_samples}

---
Assess this lesson as a curriculum expert. Consider:
1. Pedagogical clarity and scaffolding in the Learning items
2. Quality and coverage of Practice items
3. Exit ticket alignment with learning objectives
4. Consistency between teacher observations and item content
5. Specific content issues (language, visuals, cognitive load, unit errors)

Respond ONLY with a valid JSON object — no markdown fences, no extra text:
{{
  "final_rating": "Good" or "Average" or "Bad",
  "overall_summary": "2-3 sentence expert assessment",
  "strengths": ["strength 1", "strength 2"],
  "concerns": ["concern 1", "concern 2"],
  "recommendations": ["actionable fix 1", "actionable fix 2", "actionable fix 3"],
  "confidence": "High" or "Medium" or "Low",
  "confidence_note": "why this confidence level"
}}"""


# ── Claude call ────────────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> dict:
    # LLM synthesis routes through the Cuemath LLM gateway (LiteLLM proxy fronting
    # Bedrock), which exposes an Anthropic-shaped /v1/messages endpoint using
    # virtual-key auth — no direct Anthropic key. Same request/response shape as
    # api.anthropic.com, so only the URL and key source change.
    if not LLM_API_KEY:
        return {"error": "LLM_API_KEY not configured"}

    payload = json.dumps({
        "model":      LLM_MODEL,
        "max_tokens": 2048,
        # Disable adaptive thinking so the small output budget isn't consumed by
        # thinking tokens — this is a single-shot structured-JSON synthesis.
        "thinking":   {"type": "disabled"},
        "messages":   [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LLM_GATEWAY_BASE_URL.rstrip('/')}/v1/messages",
        data=payload, method="POST",
    )
    req.add_header("x-api-key",         LLM_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type",      "application/json")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data  = json.loads(resp.read().decode("utf-8"))
            text  = data["content"][0]["text"]
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                return json.loads(match.group())
            return {"error": f"No JSON in response: {text[:300]}"}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {exc.code}: {body[:300]}"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Cache ──────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            cutoff = time.time() - _CACHE_TTL
            return {k: v for k, v in data.items()
                    if v.get("_generated_at", 0) > cutoff}
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# ── Public entry ───────────────────────────────────────────────────────────────

def generate_ai_expert_review(
    flow_b_result:  dict,
    flow_a_results: list,
    ai_doc_reviews: dict,
    force:          bool = False,
) -> dict:
    """Return (possibly cached) AI expert review for a Complete lesson.

    Safe to call even when API keys are missing — returns {error: ...} in that case.
    """
    activity_ref = flow_b_result.get("activity_ref", "")
    if not activity_ref:
        return {}

    # Stable cache key: ref + hash of teacher names + weighted score
    sig = hashlib.sha256(json.dumps({
        "ref":     activity_ref,
        "teachers": sorted(flow_b_result.get("teacher_names", [])),
        "score":    flow_b_result.get("weighted_score", 0),
    }, sort_keys=True).encode()).hexdigest()[:16]
    cache_key = f"{activity_ref}|{sig}"

    cache = _load_cache()
    if not force and cache_key in cache:
        return cache[cache_key]

    # ── Fetch Learnosity item content ────────────────────────────────────────
    item_refs     = [r.get("item_ref", "") for r in flow_a_results if r.get("item_ref")]
    items_raw     = _fetch_items_content(item_refs)
    items_summary = [_summarise_item(i) for i in items_raw]

    # ── Build prompt inputs ──────────────────────────────────────────────────
    items_text   = _format_items_text(items_summary)
    teacher_text = _format_teacher_text(
        flow_b_result.get("_per_teacher_data", []) or [],
        flow_a_results,
    )
    doc_samples  = _format_doc_samples(ai_doc_reviews)
    lesson_meta  = {
        "activity_ref": activity_ref,
        "grade":   flow_b_result.get("grade", ""),
        "chapter": flow_b_result.get("chapter", ""),
        "lesson":  flow_b_result.get("lesson", ""),
    }

    prompt = _build_prompt(lesson_meta, items_text, teacher_text,
                           flow_b_result.get("section_ratings", {}), doc_samples)

    result = _call_claude(prompt)
    if result.get("error"):
        print(f"[ai_expert_review] {activity_ref}: {result['error']}")
        return result

    result["_generated_at"]     = time.time()
    result["_activity_ref"]     = activity_ref
    result["_items_reviewed"]   = len(items_summary)
    result["_learnosity_found"] = len(items_raw) > 0

    cache[cache_key] = result
    _save_cache(cache)
    return result
