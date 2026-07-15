"""No-LLM audit: for every Complete lesson, fetch its sheet item refs from
Learnosity and report how many are tagged Learning vs not — so we know whether
existing AI reviews need regenerating under the learning-only filter, and for
which lessons. In-container only. Never raises."""
from __future__ import annotations

import concurrent.futures


def main() -> None:
    try:
        from utils.cache import all_results
        from processing.ai_expert_review import (
            _fetch_items_content, _is_learning_item, _item_type_tag,
        )
        res = all_results()
        comp = [r for r in res.values() if r.get("status") == "Complete"]
        print(f"FAUDIT: {len(comp)} complete lessons", flush=True)

        def _check(r):
            refs = [x.get("item_ref", "") for x in r.get("flow_a_results", []) if x.get("item_ref")]
            if not refs:
                return (r.get("activity_ref", ""), 0, [])
            items = _fetch_items_content(refs)
            nl = [(it.get("reference", ""), _item_type_tag(it)) for it in items
                  if not _is_learning_item(it)]
            return (r.get("activity_ref", ""), len(items), nl)

        total_items = total_nl = lessons_nl = 0
        examples = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for ref, nitems, nl in pool.map(_check, comp):
                total_items += nitems
                total_nl += len(nl)
                if nl:
                    lessons_nl += 1
                    if len(examples) < 10:
                        examples.append((ref, nl[:3]))

        print(f"FAUDIT: items_fetched={total_items} non_learning={total_nl} "
              f"lessons_with_nonlearning={lessons_nl}/{len(comp)}", flush=True)
        for ref, nl in examples:
            print(f"FAUDIT   {ref}: {nl}", flush=True)
        print("FAUDIT: done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"FAUDIT ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
