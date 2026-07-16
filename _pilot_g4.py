"""One-off: pilot the new per-item, content-only AI review on a SINGLE lesson.
Clears all cached AI reviews, regenerates the target lesson per-item, then
recomputes health so ONLY the target lesson includes the AI (20%) component.
In-container (Learnosity). Never raises."""
from __future__ import annotations

TARGET = "US-G4-Determine-Median-and-Range-of-Data-Sets-V3-1.W05"


def main() -> None:
    try:
        from processing.ai_expert_review import (
            _load_cache, _save_cache, _CACHE_LOCK,
            generate_ai_expert_review, get_cached_ai_reviews,
        )
        from processing.pipeline import run_pipeline
        from utils.cache import all_results

        # 1. Clear ALL cached AI reviews — AI is piloted on the target only.
        with _CACHE_LOCK:
            _save_cache({})
        print("PILOT: cleared AI review cache", flush=True)

        # 2. Regenerate the target lesson (per-item, content-only).
        res = all_results()
        r = res.get(TARGET)
        if not r:
            print(f"PILOT: {TARGET} not in results", flush=True)
        else:
            out = generate_ai_expert_review(r, r.get("flow_a_results", []), {}, force=True)
            if out.get("error"):
                print(f"PILOT: target error — {out['error']}", flush=True)
            else:
                items = out.get("items") or []
                print(f"PILOT: target ai_score={out.get('ai_score')} rating={out.get('final_rating')} "
                      f"items_reviewed={len(items)} learnosity={out.get('_learnosity_found')}", flush=True)
                for it in items:
                    if isinstance(it, dict):
                        print(f"PILOT   item {it.get('reference')}: {it.get('score')} "
                              f"checks={it.get('checks')}", flush=True)

        # 3. Recompute health everywhere: target gains AI, all others drop it.
        run_pipeline(force=False, progress=lambda p, t="": None,
                     warn=lambda m: print(f"PILOT warn: {m}", flush=True))
        print(f"PILOT: cached AI reviews now = {len(get_cached_ai_reviews())} (expect 1)", flush=True)
        print("PILOT: done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"PILOT EXC {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
