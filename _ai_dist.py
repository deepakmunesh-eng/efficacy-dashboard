"""Read-only: print the distribution of AI-review scores across all cached
reviews. In-container (reads the /data cache). Never raises."""
from __future__ import annotations


def main() -> None:
    try:
        from collections import Counter
        from processing.ai_expert_review import get_cached_ai_reviews

        revs = get_cached_ai_reviews()
        scores = [r.get("ai_score") for r in revs.values()
                  if isinstance(r.get("ai_score"), (int, float))]
        print(f"AIDIST: {len(revs)} reviews, {len(scores)} scored", flush=True)
        if not scores:
            print("AIDIST: no scores", flush=True); return

        scores.sort()
        n = len(scores)
        mean = round(sum(scores) / n, 2)
        median = scores[n // 2] if n % 2 else round((scores[n//2-1] + scores[n//2]) / 2, 2)
        good = sum(1 for s in scores if s >= 4.0)
        avg = sum(1 for s in scores if 2.5 <= s < 4.0)
        bad = sum(1 for s in scores if s < 2.5)
        print(f"AIDIST: min={min(scores)} max={max(scores)} mean={mean} median={median}", flush=True)
        print(f"AIDIST bands: Good(>=4.0)={good}  Average(2.5-3.9)={avg}  Bad(<2.5)={bad}", flush=True)

        buckets = Counter(round(s * 2) / 2 for s in scores)   # nearest 0.5
        for b in sorted(buckets):
            bar = "#" * buckets[b]
            print(f"AIDIST  {b:.1f} : {buckets[b]:>3}  {bar}", flush=True)
        # per-item score spread too
        item_scores = [it.get("score") for r in revs.values() for it in (r.get("items") or [])
                       if isinstance(it, dict) and isinstance(it.get("score"), (int, float))]
        if item_scores:
            ig = sum(1 for s in item_scores if s >= 4.0)
            ia = sum(1 for s in item_scores if 2.5 <= s < 4.0)
            ib = sum(1 for s in item_scores if s < 2.5)
            print(f"AIDIST per-item ({len(item_scores)} items): Good={ig} Average={ia} Bad={ib}", flush=True)
        print("AIDIST done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"AIDIST ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
