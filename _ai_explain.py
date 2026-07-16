"""Read-only: show HOW a lesson's AI score is derived — per-item scores, each
item's 5-check verdicts + one-line verdict, and the mean arithmetic. Picks a few
lessons at target scores. In-container. Never raises."""
from __future__ import annotations

TARGET_SCORES = {2.7, 2.9, 3.8}


def main() -> None:
    try:
        from processing.ai_expert_review import get_cached_ai_reviews
        revs = get_cached_ai_reviews()

        picked = {}
        for ref, r in revs.items():
            s = r.get("ai_score")
            if isinstance(s, (int, float)) and round(float(s), 1) in TARGET_SCORES and round(float(s), 1) not in picked:
                picked[round(float(s), 1)] = (ref, r)
            if len(picked) == len(TARGET_SCORES):
                break

        for sc in sorted(picked):
            ref, r = picked[sc]
            items = r.get("items") or []
            item_scores = [it.get("score") for it in items if isinstance(it, dict)]
            print(f"AIEXP ============ {ref}  → lesson AI = {r.get('ai_score')} ({r.get('final_rating')})", flush=True)
            print(f"AIEXP   mean of items {item_scores} = {r.get('ai_score')}", flush=True)
            for it in items:
                if not isinstance(it, dict):
                    continue
                ch = it.get("checks") or {}
                nchange = sum(1 for v in ch.values() if str(v).lower().startswith("chang"))
                print(f"AIEXP   item {it.get('reference','')}: score={it.get('score')} "
                      f"| changes={nchange}/5 | checks={ch}", flush=True)
                print(f"AIEXP      verdict: {(it.get('verdict') or '')[:200]}", flush=True)
        print("AIEXP done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"AIEXP ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
