"""Read-only: AI review coverage. How many lessons are Complete vs Pending, how
many have a cached AI review, and how many lessons (incl. Pending) actually have
learning item refs in the sheet (i.e. are candidates for a content review).
In-container. Never raises."""
from __future__ import annotations


def main() -> None:
    try:
        from utils.cache import all_results
        from processing.ai_expert_review import get_cached_ai_reviews
        from data.sheets_reader import fetch_all_lesson_reviews
        from utils.deduplication import deduplicate_reviews, group_by_lesson

        res = all_results()
        complete = [r for r in res.values() if r.get("status") == "Complete"]
        pending  = [r for r in res.values() if r.get("status") != "Complete"]
        ai = set(get_cached_ai_reviews().keys())
        print(f"COV: total={len(res)} complete={len(complete)} pending={len(pending)} "
              f"cached_ai={len(ai)}", flush=True)

        comp_no_ai = [r["activity_ref"] for r in complete if r["activity_ref"] not in ai]
        print(f"COV: complete WITHOUT ai = {len(comp_no_ai)}: {comp_no_ai[:6]}", flush=True)

        # Item refs per lesson straight from the sheet (works for Pending too).
        rows = fetch_all_lesson_reviews()
        lessons = group_by_lesson(deduplicate_reviews(rows))
        def item_refs(ls):
            return {(x.get("item_ref") or "").strip() for x in ls if (x.get("item_ref") or "").strip()}
        pend_with_items = 0
        for r in pending:
            refs = item_refs(lessons.get(r["activity_ref"], []))
            if refs:
                pend_with_items += 1
        print(f"COV: pending lessons WITH item refs in sheet = {pend_with_items}/{len(pending)}", flush=True)
        # sample a couple pending refs + counts
        shown = 0
        for r in pending:
            refs = item_refs(lessons.get(r["activity_ref"], []))
            if refs and shown < 4:
                print(f"COV   pending {r['activity_ref']}: {len(refs)} item refs", flush=True)
                shown += 1
        print("COV done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"COV ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
