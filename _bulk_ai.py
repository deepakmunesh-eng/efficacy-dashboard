"""Bulk-generate AI reviews for every Complete lesson, then fold the 1-5 AI
scores into health. Meant to run INSIDE the Railway container (whitelisted IP →
real Learnosity content; writes to the /data cache). Runs in the background so it
never blocks the app. Prints progress to the logs; never raises."""
from __future__ import annotations

import concurrent.futures


def main() -> None:
    try:
        from utils.cache import all_results
        from processing.ai_expert_review import generate_ai_expert_review
        from processing.pipeline import run_pipeline
        try:
            from data.ai_review_reader import fetch_ai_reviews
            ai_doc = fetch_ai_reviews()
        except Exception:  # noqa: BLE001
            ai_doc = {}

        results = all_results()
        comp = [r for r in results.values() if r.get("status") == "Complete"]
        print(f"BULKAI: start — {len(comp)} complete lessons", flush=True)

        def _gen(r):
            ref = r.get("activity_ref", "")
            try:
                out = generate_ai_expert_review(r, r.get("flow_a_results", []), ai_doc)
                if out.get("error"):
                    return ref, f"ERR:{str(out['error'])[:50]}", out.get("_learnosity_found")
                return ref, out.get("ai_score"), out.get("_learnosity_found")
            except Exception as exc:  # noqa: BLE001
                return ref, f"EXC:{exc}", None

        done = 0
        learnosity_hits = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for ref, score, found in pool.map(_gen, comp):
                done += 1
                if found:
                    learnosity_hits += 1
                if done % 10 == 0 or done == len(comp):
                    print(f"BULKAI: {done}/{len(comp)} (learnosity_ok={learnosity_hits}) "
                          f"last {ref} -> {score}", flush=True)

        # Fold the freshly-cached AI scores into each lesson's health (one pass,
        # one save). run_pipeline reads them via get_cached_ai_score.
        print("BULKAI: folding AI scores into health…", flush=True)
        run_pipeline(force=False, progress=lambda p, t="": None,
                     warn=lambda m: print(f"BULKAI WARN: {m}", flush=True))
        print(f"BULKAI: done — {done} reviews, {learnosity_hits} with Learnosity content", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"BULKAI: ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
