"""One-off: dump a few cached AI reviews (full) to the logs so we can verify
they are grounded in the gold-standard framework (five checks + score bands) and
in the actual Learnosity item content. Safe boot step; never raises."""
from __future__ import annotations


def main() -> None:
    try:
        from processing.ai_expert_review import get_cached_ai_reviews
        revs = get_cached_ai_reviews()
        print(f"DUMP: {len(revs)} cached reviews total", flush=True)

        # Prefer reviews that actually read Learnosity content; show a low, mid
        # and high score so the framework's differentiation is visible.
        with_content = [(ref, r) for ref, r in revs.items()
                        if r.get("_learnosity_found") and r.get("ai_score") is not None]
        with_content.sort(key=lambda kv: kv[1].get("ai_score") or 0)
        picks = []
        if with_content:
            picks = [with_content[0], with_content[len(with_content) // 2], with_content[-1]]

        for ref, r in picks:
            print("DUMP ==================================================", flush=True)
            print(f"DUMP ref={ref} score={r.get('ai_score')} rating={r.get('final_rating')} "
                  f"learnosity_found={r.get('_learnosity_found')} items_reviewed={r.get('_items_reviewed')}",
                  flush=True)
            print(f"DUMP confidence_note: {(r.get('confidence_note') or '')[:200]}", flush=True)
            for k, c in (r.get("checks") or {}).items():
                if isinstance(c, dict):
                    print(f"DUMP check {k}: {c.get('status')} :: {(c.get('comment') or '')[:170]}", flush=True)
            for i, con in enumerate((r.get("concerns") or [])[:2]):
                print(f"DUMP concern{i+1}: {str(con)[:180]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"DUMP ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
