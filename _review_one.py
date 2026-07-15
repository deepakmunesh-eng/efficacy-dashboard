"""One-off: regenerate the CONTENT-ONLY AI review for a single lesson, drop any
old (teacher-based) cached review for it, fold the new score into health, and
print the full review to the logs. In-container (Learnosity). Never raises."""
from __future__ import annotations

TARGET = "US-G4-Determine-Median-and-Range-of-Data-Sets-V3-1.W05"


def main() -> None:
    try:
        from utils.cache import all_results, save_all_results
        from processing.ai_expert_review import (
            generate_ai_expert_review, _load_cache, _save_cache, _CACHE_LOCK,
        )
        from processing.health import compute_health

        res = all_results()
        r = res.get(TARGET)
        if not r:
            print(f"REVONE: lesson {TARGET} not in results", flush=True)
            return

        # Remove any stale (teacher-based) cached review for this lesson so only
        # the new content-only review remains.
        with _CACHE_LOCK:
            c = _load_cache()
            for k in [k for k in c if k.startswith(TARGET + "|")]:
                del c[k]
            _save_cache(c)

        out = generate_ai_expert_review(r, r.get("flow_a_results", []), {}, force=True)
        if out.get("error"):
            print(f"REVONE ERROR: {out['error']}", flush=True)
            return

        print(f"REVONE score={out.get('ai_score')} rating={out.get('final_rating')} "
              f"learnosity_found={out.get('_learnosity_found')} "
              f"items_reviewed={out.get('_items_reviewed')} items_fetched={out.get('_items_fetched')}",
              flush=True)
        print(f"REVONE confidence={out.get('confidence')} :: {out.get('confidence_note','')}", flush=True)
        print(f"REVONE summary: {(out.get('overall_summary') or '')[:300]}", flush=True)
        for k, cc in (out.get("checks") or {}).items():
            if isinstance(cc, dict):
                print(f"REVONE check {k}: {cc.get('status')} :: {(cc.get('comment') or '')[:220]}", flush=True)
        for i, s in enumerate((out.get("strengths") or [])[:3]):
            print(f"REVONE strength{i+1}: {str(s)[:200]}", flush=True)
        for i, cn in enumerate((out.get("concerns") or [])[:3]):
            print(f"REVONE concern{i+1}: {str(cn)[:200]}", flush=True)

        # Fold the new score into this lesson's health.
        classroom = r.get("section_ratings", {}).get("classroom_review", {}).get("score") or None
        health = compute_health(teacher=r.get("teacher_score") or None,
                                classroom=classroom, exit_data=None, ai=out.get("ai_score"))
        r["health"] = health
        r["weighted_score"] = health["score"]
        r["final_rating"] = health["rating"]
        save_all_results(res)
        print(f"REVONE health={health['score']} ({health['rating']}) weights={health['weights']}", flush=True)
        print("REVONE done", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"REVONE EXC {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
