"""
Rule-based scoring engine.
Maps teacher dropdown responses → numeric scores → RAG ratings.
No external API required.
"""
from __future__ import annotations

from utils.helpers import safe_float

# ── Keyword score tables ───────────────────────────────────────────────────────
# Each entry: (keywords_to_match, score_0_to_5)
# Matched case-insensitively on the full field value.

_UNDERSTANDING_SCORES = [
    (["most", "all", "clear", "well", "strong", "excellent", "fully"], 5.0),
    (["many", "majority", "good", "largely", "mostly"],                4.0),
    (["some", "half", "partially", "moderate", "average"],             3.0),
    (["few", "struggle", "difficulty", "poor", "limited"],             2.0),
    (["rarely", "not", "very few", "none", "failed"],                  1.0),
]

_EXAMPLES_SCORES = [
    (["sufficient", "enough", "good", "excellent", "adequate", "well", "plenty"], 5.0),
    (["mostly", "largely", "fair", "reasonable"],                                  4.0),
    (["some", "moderate", "average", "partial"],                                   3.0),
    (["more", "lacking", "insufficient", "few", "need"],                           2.0),
    (["none", "very few", "missing", "no examples"],                               1.0),
]

_ENGAGEMENT_SCORES = [
    (["very engaging", "highly engaging", "excellent", "loved", "exciting"],  5.0),
    (["engaging", "fun", "interesting", "good", "enjoyable"],                 4.0),
    (["somewhat", "moderate", "average", "okay", "decent"],                   3.0),
    (["needs", "improve", "lacking", "not very", "boring", "dull"],           2.0),
    (["not engaging", "very boring", "disengaged", "poor"],                   1.0),
]

_LANGUAGE_SCORES = [
    (["appropriate", "clear", "excellent", "suitable", "well-written", "perfect"], 5.0),
    (["mostly clear", "good", "mostly appropriate", "generally"],                   4.0),
    (["average", "okay", "moderate", "acceptable"],                                 3.0),
    (["complex", "difficult", "unclear", "confusing", "hard to understand"],        2.0),
    (["too simple", "very unclear", "inappropriate", "very complex"],               1.0),
]

# Length is a modifier, not a direct score
_LENGTH_MODIFIER = {
    "just right": 1.0,
    "appropriate": 1.0,
    "too long": 0.75,
    "too short": 0.75,
    "very long": 0.6,
    "very short": 0.6,
}

# Practice/Exit ticket: look for positive vs negative signals in multi-select text
_POSITIVE_PRACTICE = [
    "good variety", "relevant", "real-world", "engaging", "appropriate difficulty",
    "brain teaser", "challenging", "well-balanced", "reasoning", "application",
]
_NEGATIVE_PRACTICE = [
    "too easy", "too hard", "repetitive", "limited variety", "not engaging",
    "poor quality", "unclear", "incorrect", "needs improvement",
]

# Classroom Q1-Q5, Q7-Q9 are 4-option dropdowns: map option text to 1–4 scale
_CLASSROOM_OPTION_SCORES = {
    # Common 4-option patterns
    "strongly agree":    4, "agree":          3, "disagree":      2, "strongly disagree": 1,
    "excellent":         4, "good":           3, "average":       2, "poor":              1,
    "always":            4, "usually":        3, "sometimes":     2, "rarely":            1,
    "very engaging":     4, "engaging":       3, "somewhat":      2, "not engaging":      1,
    "well":              4, "mostly":         3, "partially":     2, "not well":          1,
    "very appropriate":  4, "appropriate":    3, "somewhat":      2, "not appropriate":   1,
    "too challenging":   2, "just right":     4, "too easy":      2, "very easy":         1,
}


def _keyword_score(text: str, table: list) -> float:
    """Return the score for the first matching keyword group, else 3.0 (neutral)."""
    t = (text or "").lower().strip()
    if not t:
        return 3.0
    for keywords, score in table:
        if any(kw in t for kw in keywords):
            return score
    return 3.0


def _length_modifier(text: str) -> float:
    t = (text or "").lower().strip()
    for key, mod in _LENGTH_MODIFIER.items():
        if key in t:
            return mod
    return 1.0


def _practice_score(text: str) -> float:
    """Score practice/exit-ticket quality from multi-select free text."""
    t = (text or "").lower()
    pos = sum(1 for kw in _POSITIVE_PRACTICE if kw in t)
    neg = sum(1 for kw in _NEGATIVE_PRACTICE if kw in t)
    if pos == 0 and neg == 0:
        return 3.0
    total = pos + neg
    return 1.0 + (pos / total) * 4.0  # scales 1.0–5.0


def _classroom_option_score(text: str) -> float:
    t = (text or "").lower().strip()
    for key, val in _CLASSROOM_OPTION_SCORES.items():
        if key in t:
            return float(val)
    return 2.5  # neutral


def score_item_row(row: dict) -> dict[str, float]:
    """Compute dimension scores for a single teacher's item-level row."""
    understanding = _keyword_score(row.get("understanding", ""), _UNDERSTANDING_SCORES)
    examples      = _keyword_score(row.get("examples_practice", ""), _EXAMPLES_SCORES)
    engagement    = _keyword_score(row.get("engagement", ""), _ENGAGEMENT_SCORES)
    language      = _keyword_score(row.get("language", ""), _LANGUAGE_SCORES)
    length_mod    = _length_modifier(row.get("length", ""))

    raw = (understanding + examples + engagement + language) / 4.0
    return {
        "understanding": understanding,
        "examples":      examples,
        "engagement":    engagement,
        "language":      language,
        "length_mod":    length_mod,
        "item_score":    round(raw * length_mod, 2),
    }


def score_section_row(row: dict) -> dict[str, float]:
    """Compute practice + exit ticket scores from a teacher's first (section-level) row."""
    practice    = _practice_score(
        (row.get("practice_quality", "") or "") + " " + (row.get("practice_observations", "") or "")
    )
    exit_ticket = _practice_score(
        (row.get("exit_ticket_quality", "") or "") + " " + (row.get("exit_ticket_observations", "") or "")
    )
    # Only record overall_rating if the teacher explicitly filled it in.
    # Empty/missing → 0.0 so the UI can distinguish "not provided" from "gave 3".
    raw = (row.get("overall_rating") or "").strip()
    overall = safe_float(raw, 0.0) if raw else 0.0
    return {
        "practice_score":    round(practice, 2),
        "exit_ticket_score": round(exit_ticket, 2),
        "overall_rating":    overall,
    }


def score_classroom_record(record: dict) -> float:
    """Aggregate a single classroom review record to a 1–5 score."""
    q_scores = []
    for q in ["learning_q1", "learning_q2", "learning_q3", "learning_q4", "learning_q5",
              "practice_q7", "practice_q8", "practice_q9"]:
        val = record.get(q, "")
        if val:
            s = _classroom_option_score(val)
            if s:
                q_scores.append(s / 4.0 * 5.0)  # rescale 1–4 → 1.25–5.0

    q11 = safe_float(record.get("overall_effectiveness"), 0.0)
    if q11:
        q_scores.append(q11)

    return round(sum(q_scores) / len(q_scores), 2) if q_scores else 3.0


def detect_divergences(teacher_scores: list[dict[str, float]]) -> list[dict]:
    """Flag dimensions where teachers differ by > 1.5 points."""
    if len(teacher_scores) < 2:
        return []
    dimensions = ["understanding", "examples", "engagement", "language"]
    divergences = []
    for dim in dimensions:
        vals = [t.get(dim, 3.0) for t in teacher_scores]
        spread = max(vals) - min(vals)
        if spread > 1.5:
            divergences.append({
                "dimension": dim.title(),
                "spread": round(spread, 1),
                "description": (
                    f"Teachers differ by {spread:.1f} points on {dim}. "
                    f"Scores: {', '.join(str(v) for v in vals)}"
                ),
                "teacher_positions": " | ".join(
                    f"T{i+1}: {v}" for i, v in enumerate(vals)
                ),
            })
    return divergences


def rag_from_score(score: float) -> str:
    if score >= 4.0:
        return "Good"
    if score >= 2.5:
        return "Average"
    return "Bad"
