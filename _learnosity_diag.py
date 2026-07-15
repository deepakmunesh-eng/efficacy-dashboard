"""Diagnose 'partial Learnosity content'. For a few lessons, reproduce the item
fetch and report, per item: how many widget question-refs the item declares vs
how many questions the gateway actually returned — so we can see where content
is lost (item not resolving, no widgets, or missing questions). Runs in-container
(whitelisted IP). Safe boot step; never raises."""
from __future__ import annotations

TARGETS = [
    "US-G2-Mixed-Unit-Measurements-V3-1.W04",
    "Apply-Percents-to-Discount-Tax-and-Decision Making-V3.1-001",
    "Classify-Quadrilaterals-Based-on-Their-Properties.W01-V3.1",
]


def main() -> None:
    try:
        from utils.cache import all_results
        from processing.ai_expert_review import (
            _gateway_post, _item_body, _summarise_item, _fetch_items_content,
        )
        results = all_results()

        for ref in TARGETS:
            r = results.get(ref) or {}
            item_refs = [x.get("item_ref", "") for x in r.get("flow_a_results", []) if x.get("item_ref")]
            print(f"DIAG ===== {ref}", flush=True)
            print(f"DIAG   flow_a item_refs = {len(item_refs)}: {item_refs}", flush=True)
            if not item_refs:
                continue

            # 1. raw items
            items = []
            for i in range(0, len(item_refs), 50):
                data = _gateway_post("/learnosity/v2/items/",
                                     {"request_data": {"references": item_refs[i:i+50], "limit": 50}})
                if isinstance(data, list):
                    items.extend(x for x in data if isinstance(x, dict))
            returned = {it.get("reference", "") for it in items}
            missing = [x for x in item_refs if x not in returned]
            print(f"DIAG   items returned = {len(items)} | refs NOT resolved = {missing}", flush=True)

            # 2. per-item widget refs
            all_qrefs = []
            per_item = []
            for it in items:
                defn = _item_body(it).get("definition") or {}
                widgets = defn.get("widgets") or it.get("questions") or []
                wrefs = [w.get("reference") for w in widgets if isinstance(w, dict) and w.get("reference")]
                per_item.append((it.get("reference", ""), len(widgets), len(wrefs)))
                all_qrefs.extend(wrefs)
            for iref, nwid, nref in per_item:
                print(f"DIAG   item {iref}: widgets={nwid} widget_refs={nref}", flush=True)

            # 3. questions resolved
            qmap = set()
            for i in range(0, len(all_qrefs), 200):
                qdata = _gateway_post("/learnosity/v2/questions/",
                                      {"question_references": all_qrefs[i:i+200]})
                for q in (qdata or []):
                    if isinstance(q, dict):
                        qref = q.get("reference") or (q.get("data") or {}).get("reference")
                        if qref:
                            qmap.add(qref)
            resolved = sum(1 for x in all_qrefs if x in qmap)
            print(f"DIAG   question refs total={len(all_qrefs)} resolved={resolved} "
                  f"missing={len(all_qrefs) - resolved}", flush=True)

            # 4. final shaped (what the prompt actually gets)
            shaped = _fetch_items_content(item_refs)
            tot_q = sum(len(s.get("questions", [])) for s in shaped)
            print(f"DIAG   SHAPED items={len(shaped)} total_questions_in_prompt={tot_q}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"DIAG ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
