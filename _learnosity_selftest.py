"""One-shot container-side check: do the sheet's item_refs resolve to real
Learnosity content through the data gateway? Prints a concise result to the
Railway logs. Safe to run at boot (never raises)."""
from __future__ import annotations

import sys

try:
    from data.sheets_reader import fetch_all_lesson_reviews
    from processing.ai_expert_review import _fetch_items_content, _summarise_item

    print("LEARNOSITY-SELFTEST: start", flush=True)
    rows = fetch_all_lesson_reviews()
    refs, seen = [], set()
    for r in rows:
        ir = (r.get("item_ref") or "").strip()
        if ir and ir not in seen:
            seen.add(ir)
            refs.append(ir)
        if len(refs) >= 8:
            break
    print(f"LEARNOSITY-SELFTEST: sample item_refs = {refs}", flush=True)

    items = _fetch_items_content(refs)
    print(f"LEARNOSITY-SELFTEST: items returned = {len(items)}", flush=True)
    for it in items[:3]:
        s = _summarise_item(it)
        print(f"LEARNOSITY-SELFTEST: item {s['reference']} | {s['section']} | "
              f"questions={s['question_count']} | title={(s['title'] or '')[:50]}",
              flush=True)
    print("LEARNOSITY-SELFTEST: done", flush=True)
except Exception as exc:  # noqa: BLE001
    print(f"LEARNOSITY-SELFTEST: ERROR {type(exc).__name__}: {exc}", flush=True)

sys.exit(0)
