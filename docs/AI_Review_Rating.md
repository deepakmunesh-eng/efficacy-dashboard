# AI Review Rating — How It Works

How the dashboard produces the **AI review** score for a lesson (the **20%**
component of lesson health). This is an **independent, content-only** review of
the lesson's **learning items**, judged against the gold standard — it does **not**
use teacher feedback, teacher ratings, or reported errors.

Code: `processing/ai_expert_review.py` · Rubric: `data/learning_item_framework.md`
· Exemplars: `gold-standard-items.txt` · LLM: Cuemath LLM gateway (`claude-sonnet`).

---

## 1. What gets reviewed

- Only the lesson's **learning items** — specifically items tagged
  **`Item Type: Learning`** in Learnosity (`_is_learning_item`). Practice /
  mini-quiz / exit-ticket items are excluded.
- The item **references come from the Google review sheet** (the `item_ref`
  column). For each ref we fetch the full item content from Learnosity through
  the Cuemath data gateway.
- **Every widget** of each item is sent to the model (`_summarise_widget`) with:
  stimulus/instruction, the question template (with `{{blank}}` = response box),
  options, **correct answer(s)**, hints, teacher-tips/Cue-Don't-Tell, and sample
  answer. Only raw HTML is stripped; nothing is truncated to a sample.
- The model also receives the **review framework** (the six dimensions + bands)
  and the **gold-standard items** (exemplars with justifications) as the bar.

> If Learnosity content for a lesson can't be fetched, no content review is
> produced (the AI component is simply left out and its weight redistributed).

---

## 2. The five checks (per learning item)

For each item the model gives a verdict — **`ok`** or **`change`** — on:

| Check | What it looks at |
|---|---|
| **Flow** | sequencing; known→unknown, concrete→abstract; each widget sets up the next |
| **Visuals & simulations** | do models/sims *teach* a step (vs decorate / mismatch / missing) |
| **Text load** | short, plain, age-appropriate; nothing crowded |
| **Response boxes** | sensible number/placement; not crowded before practice |
| **Accuracy** | answers/keys correct; instructions match the visuals |

Cutting across all five, the gold standard rewards **guided discovery**
(the student is led to *arrive at* the idea) and **examples + non-examples**.

---

## 3. Per-item score (1–5)

Each item gets a **holistic 1–5 score** from the model, anchored to the framework
bands:

| Score | Meaning |
|---|---|
| **5** | all five checks `ok`; genuine guided discovery; examples **and** non-examples; correct |
| **~4** | mostly working; one or two minor `change`s |
| **~3** | several `change`s, thin scaffolding, or no non-examples |
| **≤2** | passive tell-then-quiz / missing scaffolding, **or** any genuine accuracy or text-vs-visual error |

**Important:** the item score is the model's **judgment**, *not* a fixed formula
from the check count. The number of `change` verdicts correlates with the score,
but the score is **weighted by severity** — *what* is wrong matters more than
*how many*:

- A genuine **accuracy error**, **broken flow**, or **no non-examples / no guided
  discovery** pulls the score down hard.
- A light `change` (e.g. "a plot image isn't inspectable", a minor visual note)
  barely moves it.

So two items with the same number of flags can legitimately score differently.

**Observed relationship** (indicative, from live data):

| `change` checks | typical item score |
|---|---|
| 1 / 5 | ~4.0 |
| 2 / 5 | ~3.2 – 3.8 (depends on severity) |
| 3 / 5 | ~2.8 |
| 4 / 5 | ~2.5 |

---

## 4. Lesson AI score

The lesson's AI score is the **plain mean of its item scores**, rounded to one
decimal (`generate_ai_expert_review`):

```
lesson_ai_score = round( mean(item_score for each learning item), 1 )
final_rating    = Good (≥4.0) | Average (2.5–3.9) | Bad (<2.5)
```

### Worked example — G4 · Determine Median and Range → **2.7**

```
mean(2.8, 2.5, 2.8) = 2.7  (Average)
```

| Item | Score | `change` checks | Reason (summarised) |
|---|---|---|---|
| …-002 | 2.8 | 2/5 (Visuals, Boxes) | good discovery arc, but a polypad step isn't visible + a response-box issue |
| …-003 | 2.5 | 4/5 (Flow, Visuals, Boxes, Accuracy) | only one discovery moment, **no non-example**, never explains *why* you average |
| …-004 | 2.8 | 3/5 (Flow, Visuals, Boxes) | teaches range but no prior-knowledge activation, no non-example |

Two more for range: **G6 Understanding & Writing Equations → 2.9** = mean(2.5, 3.2);
**G2 Splitting Shapes Equally → 3.8** = mean(3.8, 3.5, 4.0) (its best item had only
1/5 changes).

---

## 5. How it feeds health

- The lesson AI score feeds the **AI review = 20%** component of health.
- Health = weighted blend of **Teacher Sheet 40 · Class review 30 ·
  Exit-ticket 10 · AI review 20**; any missing component's weight is dropped and
  the rest rescaled to 100% (`processing/health.compute_health`).
- On refresh, `get_cached_ai_score()` folds the cached AI score into health
  without re-calling the LLM.

---

## 6. What the model outputs (JSON, per lesson)

```json
{
  "items": [
    {
      "reference": "US-G4-...-003",
      "score": 2.5,
      "checks": {"flow":"change","visuals":"change","text_load":"ok",
                 "response_boxes":"change","accuracy":"change"},
      "verdict": "one crisp sentence — strongest point or the key fix",
      "fixes": ["short concrete fix", "short concrete fix"]
    }
  ],
  "confidence": "High|Medium|Low",
  "confidence_note": "e.g. full widget text available; plot images not inspectable"
}
```

The dashboard shows this per item in the lesson's **AI review** expander (score +
check chips ✅/🔧 + verdict + fixes).

---

## 7. Known limits / caveats

- **Images aren't inspected** — line plots, stem-and-leaf plots and other images
  are referenced but not rendered, so image-specific issues (scale, labels) show
  as an unverified `change` on Visuals and are noted in `confidence_note`.
- **Only sheet-listed items** are reviewed. Listing *every* item of an activity
  is blocked (the gateway `activities` endpoint returns 403); every reviewed ref
  is confirmed `Item Type: Learning`.
- **Distribution is clustered Average** (mean ≈ 3.3, 0 Good / mostly Average),
  because most V3.1 items are tell-then-quiz with no non-examples — the exact
  gap the gold standard penalises. It is a strict, aspirational gauge.
- The score is **model judgment**, so minor run-to-run variation is possible; a
  fully deterministic formula (start at 5.0, subtract per weighted `change`) is
  an available alternative if reproducibility is preferred over nuance.
