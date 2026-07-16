"""Read-only: Class-review (classroom) coverage. How many classroom submissions
exist, how many match a lesson, and how many lessons actually show the Class
review component. In-container. Never raises."""
from __future__ import annotations


def main() -> None:
    try:
        from data.classroom_reader import fetch_classroom_reviews, match_classroom_to_lessons
        from utils.cache import all_results

        res = all_results()
        recs = fetch_classroom_reviews()
        distinct = {(r.get("activity_ref") or "").strip() for r in recs if (r.get("activity_ref") or "").strip()}
        matched = match_classroom_to_lessons(recs, res.keys())
        print(f"COVCLS: classroom submissions={len(recs)} distinct_refs={len(distinct)} "
              f"matched_to_lessons={len(matched)}", flush=True)

        m_complete = [ref for ref in matched if (res.get(ref) or {}).get("status") == "Complete"]
        m_pending  = [ref for ref in matched if (res.get(ref) or {}).get("status") != "Complete"]
        print(f"COVCLS: matched Complete={len(m_complete)}  matched Pending={len(m_pending)}", flush=True)

        shown = [r for r in res.values()
                 if "classroom" in (r.get("health", {}).get("components", {}))]
        print(f"COVCLS: lessons SHOWING Class review in health = {len(shown)}", flush=True)
        for r in shown:
            c = r["health"]["components"]
            print(f"COVCLS   {r.get('grade')} · {r.get('lesson','')[:45]} → class {c.get('classroom')}", flush=True)
        print("COVCLS done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"COVCLS ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
