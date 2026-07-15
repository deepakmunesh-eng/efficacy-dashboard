"""One-shot recompute — runs the full scoring pipeline headless and persists
the current-logic (v12) results to the cache (/data on Railway). Used to refresh
the deployed cache to the new logic without a manual "Refresh" click. Prints a
concise summary to the logs. Never raises (safe as a boot step)."""
from __future__ import annotations


def _prog(pct, text=""):
    print(f"RECOMPUTE {int(pct):>3}% {text}", flush=True)


def main() -> None:
    try:
        from processing.pipeline import run_pipeline, _LOGIC_VERSION
        print(f"RECOMPUTE: start (logic {_LOGIC_VERSION})", flush=True)
        # force=False is enough: the logic-version is part of each lesson's hash,
        # so stale (older-logic) results all recompute, but cached Learnosity
        # content is reused rather than re-fetched.
        res = run_pipeline(force=False, progress=_prog,
                           warn=lambda m: print(f"RECOMPUTE WARN: {m}", flush=True))
        from collections import Counter
        comp = [r for r in res.values() if r.get("status") == "Complete"]
        dist = Counter(r.get("final_rating") for r in comp)
        with_cls = sum(1 for r in comp
                       if "classroom" in (r.get("health", {}).get("components", {})))
        print(f"RECOMPUTE: done total={len(res)} complete={len(comp)} "
              f"with_classroom={with_cls} dist={dict(dist)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"RECOMPUTE: ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
