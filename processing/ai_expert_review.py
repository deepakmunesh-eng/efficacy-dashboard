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
import http.client
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request

from config.settings import (
    BASE_DIR,
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
_CACHE_LOCK  = threading.Lock()   # guards the read-modify-write of the cache file
                                  # so parallel bulk generation can't clobber it


# ── Learning Item Review reference (house style + five-check rubric) ─────────────
# A curriculum reviewer compiled 5 Learnosity sheets into a plain-language
# reference ("the five things we check"). We feed it to the model as the house
# voice + rubric so the AI review reads like a teacher wrote it. The committed
# .md (pre-extracted) is preferred; we fall back to the source .docx if present.
_REVIEW_REF_MD   = BASE_DIR / "data" / "learning_review_reference.md"
_REVIEW_REF_DOCX = BASE_DIR / "review files" / "Learning Item Review - Reference Document.docx"
_reference_cache: "str | None" = None

# Gold-standard items — exemplar learning items our designers consider the bar,
# with the reasoning for why each is strong. The AI review judges the lesson's
# learning items against this standard.
_GOLD_STANDARD_TXT = BASE_DIR / "gold-standard-items.txt"
_gold_cache: "str | None" = None

# Framework derived from the gold standard — the scoring rubric (6 dimensions +
# Good/Average/Bad bands) the review applies to each learning item.
_FRAMEWORK_MD = BASE_DIR / "data" / "learning_item_framework.md"
_framework_cache: "str | None" = None


def _load_gold_standard() -> str:
    global _gold_cache
    if _gold_cache is not None:
        return _gold_cache
    try:
        _gold_cache = (_GOLD_STANDARD_TXT.read_text(encoding="utf-8")
                       if _GOLD_STANDARD_TXT.exists() else "")
    except Exception as exc:  # noqa: BLE001
        print(f"[ai_expert_review] gold-standard load failed: {exc}")
        _gold_cache = ""
    return _gold_cache


def _load_framework() -> str:
    global _framework_cache
    if _framework_cache is not None:
        return _framework_cache
    try:
        _framework_cache = (_FRAMEWORK_MD.read_text(encoding="utf-8")
                            if _FRAMEWORK_MD.exists() else "")
    except Exception as exc:  # noqa: BLE001
        print(f"[ai_expert_review] framework load failed: {exc}")
        _framework_cache = ""
    return _framework_cache


def _load_review_reference() -> str:
    global _reference_cache
    if _reference_cache is not None:
        return _reference_cache
    text = ""
    try:
        if _REVIEW_REF_MD.exists():
            text = _REVIEW_REF_MD.read_text(encoding="utf-8")
        elif _REVIEW_REF_DOCX.exists():
            import docx  # optional; only needed to read the source .docx directly
            d = docx.Document(str(_REVIEW_REF_DOCX))
            text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
    except Exception as exc:  # noqa: BLE001
        print(f"[ai_expert_review] reference load failed: {exc}")
        text = ""
    _reference_cache = text
    return text


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
#
# The gateway sits behind an IP allowlist and is dual-stack. The IP we whitelist
# (Railway's static egress IP) is IPv4, so we force every gateway request over
# IPv4 — a dual-stack host might otherwise egress over IPv6 with a non-whitelisted
# (and rotating) address and hit "IP not whitelisted".

class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        af, socktype, proto, _canon, sa = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )[0]
        sock = socket.socket(af, socktype, proto)
        if self.timeout is not None and self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(self.timeout)
        if self.source_address:
            sock.bind(self.source_address)
        sock.connect(sa)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req)


_IPV4_OPENER = urllib.request.build_opener(_IPv4HTTPSHandler())


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
    # Force IPv4 (see note above) so the whitelisted static IP is the source.
    with _IPV4_OPENER.open(req, timeout=25) as resp:
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
    """Every teacher's feedback, in full and untruncated — this is the primary
    evidence the review is built from, so nothing is dropped."""
    lines = []
    for row in per_teacher:
        name = (row.get("reviewer_name") or "Teacher").strip()
        parts = [f"**{name}**"]
        if row.get("overall_rating"):
            parts.append(f"  Overall rating: {row['overall_rating']}/5")
        if row.get("practice_quality"):
            parts.append(f"  Practice quality: {row['practice_quality']}")
        if row.get("practice_observations"):
            parts.append(f"  Practice observations: {row['practice_observations']}")
        if row.get("exit_ticket_quality"):
            parts.append(f"  Exit ticket quality: {row['exit_ticket_quality']}")
        if row.get("exit_ticket_observations"):
            parts.append(f"  Exit ticket observations: {row['exit_ticket_observations']}")
        if row.get("additional_suggestions"):
            parts.append(f"  Additional suggestions: {row['additional_suggestions']}")
        lines.append("\n".join(parts))

    for item_result in flow_a_results:
        ref    = item_result.get("item_ref", "")
        rating = item_result.get("rating", "")
        score  = float(item_result.get("score") or 0)
        if not ref:
            continue
        lines.append(f"\nLearning item {ref} — teacher consensus {rating} ({score:.1f}/5)")
        if item_result.get("rationale"):
            lines.append(f"  Rationale: {item_result['rationale']}")
        for t_data in (item_result.get("teacher_summaries") or {}).values():
            summ = (t_data.get("summary") or "").strip()
            name = (t_data.get("name") or "Teacher").strip()
            conc = (t_data.get("key_concerns") or "").strip()
            if summ and summ != "No detailed feedback provided.":
                lines.append(f"  {name}: {summ}")
            if conc:
                lines.append(f"    Key concerns: {conc}")
        for d in (item_result.get("divergences") or []):
            dim  = d.get("dimension", "")
            desc = d.get("description", "")
            if dim or desc:
                lines.append(f"  Teacher divergence — {dim}: {desc}")
    return "\n".join(lines)


def _format_error_reports(errors: list) -> str:
    """Teacher-flagged concrete defects (from the 'Errors Reported' tab). These
    are high-signal, item-specific problems — feed them in verbatim."""
    if not errors:
        return "(No specific errors were reported for this lesson.)"
    lines = []
    for e in errors:
        ref   = e.get("item_ref") or e.get("activity_ref") or ""
        num   = e.get("item_number", "")
        etype = e.get("error_type", "")
        det   = e.get("error_details", "")
        head  = f"Item {ref}" + (f" (#{num})" if num else "")
        tag   = f" [{etype}]" if etype else ""
        lines.append(f"- {head}{tag}: {det}".rstrip())
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
    errors_text: str = "",
) -> str:
    lr = section_scores.get("learning",    {})
    pr = section_scores.get("practice",    {})
    et = section_scores.get("exit_ticket", {})

    reference = _load_review_reference()
    ref_block = (
        "\n## How we review — house style & the five checks (mirror this exactly)\n"
        "The reference below is how our curriculum team reviews a learning item. "
        "Copy this VOICE: warm, plain, specific — a helpful colleague talking, not a "
        "formal rubric. Notice the five things we always check (Flow; Visuals & "
        "simulations; Text load; Response boxes; Guided example & accuracy) and how "
        "each point names the exact screen and the concrete fix.\n\n"
        f"{reference}\n"
        if reference else ""
    )

    framework = _load_framework()
    framework_block = (
        "\n## Review framework — score each learning item on these (mirror this rubric)\n"
        "This is our review framework, built from the gold standard. Apply its six "
        "dimensions and its Good/Average/Bad bands. The five checks below map onto it "
        "(Flow←flow/sequencing; Visuals←visuals & simulations; Text load←text & language; "
        "Response boxes←response design; Accuracy←accuracy; plus guided discovery & "
        "examples/non-examples run through all of them).\n\n"
        f"{framework}\n"
        if framework else ""
    )

    gold = _load_gold_standard()
    gold_block = (
        "\n## Gold-standard learning items (the bar to compare against)\n"
        "Below are exemplar items our designers consider gold-standard, each with the "
        "reasoning for why it is strong (document style, Learnosity rendering, and the "
        "justification). Judge this lesson's learning items against THIS bar — where an "
        "item falls short of what these examples do well, that is a 'Suggested change'.\n\n"
        f"{gold}\n"
        if gold else ""
    )

    return f"""You are a Cuemath curriculum reviewer. Review the LEARNING ITEMS of this K-8 math lesson exactly the way our reference document does — the same five checks, the same warm, plain, specific voice (a helpful colleague, never a formal report). Name the item/screen and say what you'd actually change.
{ref_block}{framework_block}{gold_block}
## The five checks (score EACH one)
For every learning item we look at: **Flow**, **Visuals & simulations**, **Text load**, **Response boxes**, and **Accuracy** (guided examples & correctness). For each check decide "Working well" or "Suggested change" and give a short, concrete comment in the reference voice.

## Lesson
Grade {lesson_meta.get('grade','')} | {lesson_meta.get('chapter','')} | {lesson_meta.get('lesson','')}
Activity ref: {lesson_meta.get('activity_ref','')}

## Learnosity Item Content
{items_text}

## Teacher Field Scores (3 teachers, rule-based)
Learning: {lr.get('score',0):.1f}/5 ({lr.get('rating','—')}) | Practice: {pr.get('score',0):.1f}/5 ({pr.get('rating','—')}) | Mini-Quiz: {et.get('score',0):.1f}/5 ({et.get('rating','—')})

## Teacher Feedback — use EVERY point below
This teacher feedback is your primary evidence. Use ALL of it — every teacher, every observation. Weave the recurring themes together and keep the specific, concrete points. Do not drop anyone's input.
{teacher_text}

## Errors Reported by Teachers (concrete, item-specific defects — treat as must-fix)
These are precise problems teachers flagged (wrong answers, inconsistent boxes, etc.). Reflect the important ones in the relevant check and in "concerns".
{errors_text}

## Reference expert-review examples (for tone)
{doc_samples}

---
Now write the review of the LEARNING items across the five checks. Ground everything in the evidence above; where Learnosity item content isn't available, lean on the teacher feedback rather than inventing details.

Also give a single **ai_score from 1.0 to 5.0** for the learning items overall — this is the AI component of the lesson's health (weighted 20%). Anchor it: 5.0 = all five checks working well with no real issues; ~4.0 = mostly working, one or two minor suggested changes; ~3.0 = several suggested changes or one genuine accuracy/flow problem; ≤2.0 = multiple genuine problems (wrong content, broken flow, heavy text). Be consistent with your per-check verdicts.

Respond ONLY with a valid JSON object — no markdown fences, no extra text:
{{
  "ai_score": 4.2,
  "final_rating": "Good" or "Average" or "Bad",
  "checks": {{
    "flow":           {{"status": "Working well" or "Suggested change", "comment": "..."}},
    "visuals":        {{"status": "Working well" or "Suggested change", "comment": "..."}},
    "text_load":      {{"status": "Working well" or "Suggested change", "comment": "..."}},
    "response_boxes": {{"status": "Working well" or "Suggested change", "comment": "..."}},
    "accuracy":       {{"status": "Working well" or "Suggested change", "comment": "..."}}
  }},
  "overall_summary": "2-3 sentence plain-language take",
  "strengths": ["what's genuinely working, in a teacher's voice — specific", "..."],
  "concerns": ["what needs a fix, phrased like a teacher's suggested change — name the item/screen and the concrete fix", "..."],
  "recommendations": ["specific fix 1", "specific fix 2", "specific fix 3"],
  "confidence": "High" or "Medium" or "Low",
  "confidence_note": "one line on why (e.g. based on teacher feedback only, Learnosity content not yet available)"
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


def get_cached_ai_score(activity_ref: str) -> float | None:
    """Return the AI health score (1-5) from any cached review for this lesson,
    or None if no AI review has been generated yet. Used so a refresh can fold
    the AI component (20%) into health without re-running the LLM."""
    if not activity_ref:
        return None
    cache = _load_cache()
    for key, rev in cache.items():
        if key.startswith(f"{activity_ref}|") and isinstance(rev, dict):
            if rev.get("error"):
                continue
            score = rev.get("ai_score")
            if score is not None:
                return _normalise_ai_score(rev)
    return None


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _normalise_ai_score(result: dict) -> float:
    """Clamp/derive the AI health score (1.0-5.0) for a review result."""
    raw = result.get("ai_score")
    try:
        val = float(raw)
        if 1.0 <= val <= 5.0:
            return round(val, 1)
    except (TypeError, ValueError):
        pass
    # Fallback: derive from the five per-check verdicts.
    checks = result.get("checks") or {}
    if checks:
        suggested = sum(
            1 for c in checks.values()
            if isinstance(c, dict) and "suggest" in (c.get("status", "").lower())
        )
        return round(max(1.0, 5.0 - 0.4 * suggested), 1)
    # Last resort: map the coarse rating.
    return {"Good": 4.5, "Average": 3.0, "Bad": 2.0}.get(result.get("final_rating", ""), 3.0)


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

    # No real teacher feedback → no report. Guards against generating a review
    # off blank/error-only rows. (The completeness gate should already prevent
    # this, but keep the safety net here too.)
    per_teacher = flow_b_result.get("_per_teacher_data", []) or []
    has_item_feedback = any(
        (t.get("summary") or "").strip() not in ("", "No detailed feedback provided.")
        for r in flow_a_results
        for t in (r.get("teacher_summaries") or {}).values()
    )
    if not per_teacher and not has_item_feedback:
        return {}

    error_reports = flow_b_result.get("error_reports", []) or []

    # Stable cache key: ref + hash of teacher names + weighted score + error count
    sig = hashlib.sha256(json.dumps({
        "ref":     activity_ref,
        "teachers": sorted(flow_b_result.get("teacher_names", [])),
        "score":    flow_b_result.get("weighted_score", 0),
        "errors":   len(error_reports),
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
    teacher_text = _format_teacher_text(per_teacher, flow_a_results)
    errors_text  = _format_error_reports(error_reports)
    doc_samples  = _format_doc_samples(ai_doc_reviews)
    lesson_meta  = {
        "activity_ref": activity_ref,
        "grade":   flow_b_result.get("grade", ""),
        "chapter": flow_b_result.get("chapter", ""),
        "lesson":  flow_b_result.get("lesson", ""),
    }

    prompt = _build_prompt(lesson_meta, items_text, teacher_text,
                           flow_b_result.get("section_ratings", {}), doc_samples,
                           errors_text)

    result = _call_claude(prompt)
    if result.get("error"):
        print(f"[ai_expert_review] {activity_ref}: {result['error']}")
        return result

    # Normalise the numeric AI score (1-5). If the model omitted it, derive it
    # from the five per-check verdicts (each "Suggested change" costs 0.4 off 5).
    result["ai_score"] = _normalise_ai_score(result)

    result["_generated_at"]     = time.time()
    result["_activity_ref"]     = activity_ref
    result["_items_reviewed"]   = len(items_summary)
    result["_learnosity_found"] = len(items_raw) > 0

    # Merge-and-save under a lock so concurrent bulk generation can't drop
    # each other's entries (read-modify-write of one shared JSON file).
    with _CACHE_LOCK:
        disk = _load_cache()
        disk[cache_key] = result
        _save_cache(disk)
    return result


def get_cached_ai_reviews() -> dict:
    """{activity_ref: review} for every cached, error-free AI review — used to
    preload the UI so generated reviews show without re-running the LLM."""
    out: dict = {}
    for key, rev in _load_cache().items():
        if not isinstance(rev, dict) or rev.get("error"):
            continue
        ref = rev.get("_activity_ref") or key.split("|", 1)[0]
        if ref:
            out[ref] = rev
    return out
