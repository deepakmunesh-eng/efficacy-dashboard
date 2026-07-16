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
from processing.scoring import rag_from_score

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


def _item_type_tag(item: dict) -> str:
    """The item's 'Item Type' tag value (from the shaped item's tags), or ''."""
    tags = item.get("tags") or {}
    if not isinstance(tags, dict):
        return ""
    val = tags.get("Item Type") or tags.get("item type") or tags.get("ItemType") or ""
    if isinstance(val, list):
        val = val[0] if val else ""
    return str(val)


def _is_learning_item(item: dict) -> bool:
    """True only when the item is explicitly tagged Item Type: Learning."""
    return "learning" in _item_type_tag(item).lower()


def _as_text(x, cap: int) -> str:
    """Strip HTML from a str, or compactly stringify a list/dict, then cap."""
    if x is None:
        return ""
    if not isinstance(x, str):
        try:
            x = json.dumps(x, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            x = str(x)
    return _strip_html(x)[:cap]


def _summarise_widget(q: dict) -> dict:
    """Full content of one widget — enough to review flow, scaffolding, visuals,
    text load, response design and accuracy. Nothing is dropped except raw HTML."""
    qdata = q.get("data", {}) if isinstance(q, dict) else {}
    if not isinstance(qdata, dict):
        qdata = {}
    meta = qdata.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    # Answer options: MCQ options[].label, else cloze possible_responses (grouped).
    opts: list[str] = []
    for o in (qdata.get("options") or []):
        opts.append(_as_text(o.get("label") if isinstance(o, dict) else o, 160))
    if not opts:
        for grp in (qdata.get("possible_responses") or []):
            if isinstance(grp, list):
                opts.append("[" + " / ".join(_as_text(x, 60) for x in grp) + "]")
            else:
                opts.append(_as_text(grp, 160))

    correct = (qdata.get("validation") or {}).get("valid_response") or {}
    hints = meta.get("hints") or ([qdata.get("hint")] if qdata.get("hint") else [])
    tips  = meta.get("teacher_tips") or []

    return {
        "type":          q.get("type", "") if isinstance(q, dict) else "",
        "stimulus":      _as_text(qdata.get("stimulus"), 1500),      # instructions / context / <iframe> sims
        "template":      _as_text(qdata.get("template"), 800),       # the question text with {{response}} blanks
        "options":       [o for o in opts if o][:16],
        "correct":       _as_text(correct.get("value"), 400),        # key — needed for the accuracy check
        "hints":         [_as_text(h, 300) for h in hints if h][:5],
        "teacher_tips":  [_as_text(t, 300) for t in tips if t][:5],
        "sample_answer": _as_text(meta.get("sample_answer"), 400),
    }


def _summarise_item(item: dict) -> dict:
    """Convert a raw Learnosity item into a full-content dict for the prompt —
    EVERY widget, with question text, options, correct answers, hints, tips and
    sample answers (only raw HTML is stripped)."""
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

    return {
        "reference":     item.get("reference", ""),
        "title":         item.get("title") or "",
        "section":       section,
        "item_type":     item_type,
        "question_count": len(questions),
        "questions":     [_summarise_widget(q) for q in questions],   # ALL widgets
    }


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _format_items_text(items: list[dict]) -> str:
    if not items:
        return "(Item content not available.)"
    lines = []
    for item in items:
        lines.append(f"\n### Item {item['reference']}  [{item['section']} | {item['item_type']}]  "
                     f"— {item['question_count']} widget(s), ALL shown below")
        for i, q in enumerate(item.get("questions", []), 1):
            lines.append(f"\n  ── Widget {i} [{q.get('type','')}] ──")
            if q.get("stimulus"):
                lines.append(f"    Stimulus / instruction: {q['stimulus']}")
            if q.get("template"):
                lines.append(f"    Question ( {{blank}} = response box ): {q['template']}")
            if q.get("options"):
                lines.append("    Options: " + "  ;  ".join(q["options"]))
            if q.get("correct"):
                lines.append(f"    Correct answer(s): {q['correct']}")
            for h in q.get("hints", []):
                lines.append(f"    Hint: {h}")
            for t in q.get("teacher_tips", []):
                lines.append(f"    Teacher tip / Cue-Don't-Tell: {t}")
            if q.get("sample_answer"):
                lines.append(f"    Sample answer: {q['sample_answer']}")
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


def _build_prompt(lesson_meta: dict, items_text: str) -> str:
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

    return f"""You are a Cuemath curriculum reviewer. Review the LEARNING ITEMS of this K-8 math lesson by reading the item CONTENT below and judging it against the framework and the gold standard. This is an INDEPENDENT content review: base every verdict on what the items themselves do (widgets, stimulus, visuals/simulations, hints, teacher-tips, sample answers, response design). Do NOT use or refer to teacher feedback — you are the reviewer. Use the same warm, plain, specific voice as the reference (a helpful colleague, never a formal report); name the item/screen and say what you'd actually change.
{ref_block}{framework_block}{gold_block}
## Lesson
Grade {lesson_meta.get('grade','')} | {lesson_meta.get('chapter','')} | {lesson_meta.get('lesson','')}
Activity ref: {lesson_meta.get('activity_ref','')}

## Learnosity Item Content — THIS is what you review
{items_text}

---
Review **EACH learning item SEPARATELY** (one entry per item reference above). Read that item's widgets in order and judge it against the framework's five checks — Flow, Visuals & simulations, Text load, Response boxes, Accuracy — plus guided-discovery, examples/non-examples, and the gold-standard bar.

Be **CRISP**: for each check give a one-word verdict ("ok" or "change"); one short verdict sentence for the item; and at most 2–3 short concrete fixes (only where a change is needed — omit fixes if the item is solid). No long paragraphs. If content (e.g. an image) is missing, note it briefly; do not invent details or use teacher opinion.

Score each item 1.0–5.0 against the framework bands: 5 = all checks ok, guided discovery, examples+non-examples, correct; ~4 = one/two minor changes; ~3 = several changes or thin scaffolding / no non-examples; ≤2 = passive tell-then-quiz, missing scaffolding, OR any genuine accuracy / text-vs-visual error (accuracy error caps the item at Bad).

Respond ONLY with a valid JSON object — no markdown fences, no extra text:
{{
  "items": [
    {{
      "reference": "the item reference exactly as shown above",
      "score": 3.0,
      "checks": {{"flow": "ok", "visuals": "ok", "text_load": "change", "response_boxes": "change", "accuracy": "ok"}},
      "verdict": "one crisp sentence — what's strong, or the single most important fix",
      "fixes": ["short concrete fix", "short concrete fix"]
    }}
  ],
  "confidence": "High" or "Medium" or "Low",
  "confidence_note": "one short line (e.g. full widget text available; plot images not inspectable)"
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
        # 4096 (was 2048): the 5-check structured output + strengths/concerns/
        # recommendations can exceed 2048 and truncate mid-JSON → parse error.
        "max_tokens": 4096,
        # Disable adaptive thinking so the output budget isn't consumed by
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

    # ── Fetch Learnosity item content for the sheet's item refs ──────────────
    # Look up every item reference from the sheet, then review ONLY the items
    # explicitly tagged "Item Type: Learning". This is an INDEPENDENT content
    # review — no teacher feedback / ratings / error reports are used.
    item_refs     = [r.get("item_ref", "") for r in flow_a_results if r.get("item_ref")]
    item_refs     = list(dict.fromkeys([r for r in item_refs if r]))  # unique, ordered

    # Cache key is content-driven (the item refs), NOT teacher data.
    sig = hashlib.sha256(json.dumps({
        "ref": activity_ref, "items": sorted(item_refs), "mode": "content-only-v1",
    }, sort_keys=True).encode()).hexdigest()[:16]
    cache_key = f"{activity_ref}|{sig}"

    cache = _load_cache()
    if not force and cache_key in cache:
        return cache[cache_key]

    items_raw     = _fetch_items_content(item_refs)
    learning_raw  = [it for it in items_raw if _is_learning_item(it)]
    items_summary = [_summarise_item(i) for i in learning_raw]

    # Content review needs item content. Without it (e.g. gateway unreachable),
    # there is nothing to review — return a clear, non-fatal note.
    if not items_summary:
        return {"error": "No Learnosity learning-item content available — cannot "
                         "run a content review for this lesson.",
                "_activity_ref": activity_ref}

    items_text  = _format_items_text(items_summary)
    lesson_meta = {
        "activity_ref": activity_ref,
        "grade":   flow_b_result.get("grade", ""),
        "chapter": flow_b_result.get("chapter", ""),
        "lesson":  flow_b_result.get("lesson", ""),
    }

    prompt = _build_prompt(lesson_meta, items_text)

    result = _call_claude(prompt)
    if result.get("error"):
        print(f"[ai_expert_review] {activity_ref}: {result['error']}")
        return result

    # Aggregate the per-item scores into the lesson AI score (mean).
    per_item = result.get("items") or []
    item_scores = []
    for it in per_item:
        if isinstance(it, dict):
            try:
                item_scores.append(float(it["score"]))
            except (KeyError, TypeError, ValueError):
                pass
    ai = round(sum(item_scores) / len(item_scores), 1) if item_scores else _normalise_ai_score(result)
    result["ai_score"]     = max(1.0, min(5.0, ai))
    result["final_rating"] = rag_from_score(result["ai_score"])

    result["_generated_at"]      = time.time()
    result["_activity_ref"]      = activity_ref
    result["_items_reviewed"]    = len(per_item) or len(items_summary)
    result["_items_fetched"]     = len(items_raw)
    result["_items_nonlearning"] = len(items_raw) - len(learning_raw)
    result["_learnosity_found"]  = len(learning_raw) > 0

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
