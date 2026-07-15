"""Probe: can the data gateway return the FULL item list for an activity, and
can we filter to items tagged 'Item Type: Learning'? Tries a few request shapes
for /learnosity/v2/activities/ and reports what comes back. In-container only."""
from __future__ import annotations

import json

SAMPLES = [
    "US-G2-Mixed-Unit-Measurements-V3-1.W04",
    "Classify-Quadrilaterals-Based-on-Their-Properties.W01-V3.1",
]


def _first_list_of_refs(obj, depth=0):
    """Heuristically find a list of item references in a nested activity payload."""
    if depth > 6:
        return None
    if isinstance(obj, list):
        strs = [x for x in obj if isinstance(x, str)]
        if strs and any("-" in s or " " in s for s in strs):
            return strs
        for x in obj:
            r = _first_list_of_refs(x, depth + 1)
            if r:
                return r
    elif isinstance(obj, dict):
        for k in ("items", "item_references", "itemReferences", "references"):
            if isinstance(obj.get(k), list):
                r = _first_list_of_refs(obj[k], depth + 1)
                if r:
                    return r
        for v in obj.values():
            r = _first_list_of_refs(v, depth + 1)
            if r:
                return r
    return None


def main() -> None:
    try:
        from processing.ai_expert_review import _gateway_post, _fetch_items_content, _item_body

        for act in SAMPLES:
            print(f"APROBE ===== activity {act}", flush=True)
            got_refs = None
            for path, payload in [
                ("/learnosity/v2/activities/", {"references": [act]}),
                ("/learnosity/v2/activities/", {"request_data": {"references": [act], "limit": 5}}),
                ("/learnosity/v2/activities/", {"activity_references": [act]}),
            ]:
                try:
                    data = _gateway_post(path, payload)
                    shape = (f"list[{len(data)}]" if isinstance(data, list)
                             else f"dict keys={list(data.keys())[:8]}" if isinstance(data, dict)
                             else type(data).__name__)
                    refs = _first_list_of_refs(data)
                    print(f"APROBE  payload={list(payload)[0]} -> {shape} | refs_found={len(refs) if refs else 0}", flush=True)
                    if refs and not got_refs:
                        got_refs = refs
                        print(f"APROBE   sample refs: {refs[:6]}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"APROBE  payload={list(payload)[0]} -> ERR {type(exc).__name__}: {str(exc)[:90]}", flush=True)

            # If we got the full item list, fetch items and show their Item Type tags.
            if got_refs:
                items = _fetch_items_content(got_refs)
                print(f"APROBE  full items fetched={len(items)}", flush=True)
                learning = 0
                for it in items:
                    tags = it.get("tags") or {}
                    itype = tags.get("Item Type") or tags.get("item type") or []
                    itype = itype[0] if isinstance(itype, list) and itype else str(itype)
                    if "learning" in itype.lower():
                        learning += 1
                    print(f"APROBE   item {it.get('reference','')[:55]} | Item Type={itype!r} | q={len(it.get('questions',[]))}", flush=True)
                print(f"APROBE  => {learning}/{len(items)} items tagged Learning", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"APROBE ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
