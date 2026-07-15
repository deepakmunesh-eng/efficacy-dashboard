"""Probe the studio backend (curriculum-studio-k-8) for an endpoint that returns
an activity's FULL item list (ideally with Item Type tags). In-container only —
uses internal networking + the auto-login JWT. Never raises."""
from __future__ import annotations

import json

ACT = "US-G2-Mixed-Unit-Measurements-V3-1.W04"


def _summ(txt: str) -> str:
    try:
        obj = json.loads(txt)
    except Exception:  # noqa: BLE001
        return f"(non-json) {txt[:180]}"
    if isinstance(obj, dict):
        out = {k: (f"list[{len(v)}]" if isinstance(v, list)
                   else f"dict[{len(v)}]" if isinstance(v, dict) else str(v)[:40])
               for k, v in list(obj.items())[:10]}
        return f"dict keys={out}"
    if isinstance(obj, list):
        return f"list[{len(obj)}] first={json.dumps(obj[0])[:150] if obj else '-'}"
    return str(obj)[:150]


def main() -> None:
    try:
        import requests
        from utils.auth import get_effective_auth_token, auto_auth_available

        # Internal hostname failed (port 80 / IPv6); use the public studio URL.
        RAILWAY_BACKEND_URL = "https://curriculum-studio-k-8-production.up.railway.app"
        print(f"SPROBE backend={RAILWAY_BACKEND_URL} auto_auth={auto_auth_available()}", flush=True)
        tok = get_effective_auth_token()
        print(f"SPROBE token={'yes(' + str(len(tok)) + ')' if tok else 'NO'}", flush=True)
        hdr = {"Authorization": f"Bearer {tok}"} if tok else {}

        tries = [
            ("/api/learnosity/items",      {"activity_reference": ACT}),
            ("/api/learnosity/items",      {"activityReference": ACT}),
            ("/api/learnosity/activity",   {"reference": ACT}),
            ("/api/learnosity/activities", {"references": ACT}),
            ("/api/learnosity/activity-items", {"reference": ACT}),
        ]
        for path, params in tries:
            try:
                r = requests.get(RAILWAY_BACKEND_URL + path, params=params, headers=hdr, timeout=25)
                print(f"SPROBE GET {path} {params} -> {r.status_code} | {_summ(r.text)}", flush=True)
                if r.status_code == 200:
                    try:
                        obj = r.json()
                        items = obj.get("items") if isinstance(obj, dict) else (obj if isinstance(obj, list) else None)
                        if isinstance(items, list) and items:
                            it0 = items[0]
                            if isinstance(it0, dict):
                                tags = it0.get("tags") or (it0.get("data") or {}).get("tags")
                                print(f"SPROBE   items={len(items)} first_ref={it0.get('reference')} sample_tags={json.dumps(tags)[:200]}", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        print(f"SPROBE   parse note: {exc}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"SPROBE GET {path} -> ERR {type(exc).__name__}: {str(exc)[:100]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"SPROBE ERROR {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
