"""TEMPORARY diagnostic for the IncompleteRead on large gateway reads.
Runs at container startup, logs to stdout. Safe: never raises. REMOVE after use."""
import http.client
import json
import socket
import urllib.request

import processing.ai_expert_review as air


def _mk_opener(http10: bool):
    class _Conn(http.client.HTTPSConnection):
        def connect(self):
            infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
            af, st_, proto, _c, sa = infos[0]
            s = socket.socket(af, st_, proto)
            if self.timeout is not None and self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                s.settimeout(self.timeout)
            s.connect(sa)
            self.sock = self._context.wrap_socket(s, server_hostname=self.host)
    if http10:
        _Conn._http_vsn = 10
        _Conn._http_vsn_str = "HTTP/1.0"

    class _H(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_Conn, req)
    return urllib.request.build_opener(_H())


def _call(label, opener, payload, timeout=60):
    body = json.dumps({
        "service": "LEARNOSITY", "path": "/learnosity/v2/items/", "method": "POST",
        "payload": {"domain_url": air.LEARNOSITY_MS_DOMAIN_URL, **payload},
    }).encode("utf-8")
    req = urllib.request.Request(air.DATA_GATEWAY_BASE_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {air.DATA_GATEWAY_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept-Encoding", "identity")
    try:
        resp = opener.open(req, timeout=timeout)
        h = {k.lower(): v for k, v in resp.headers.items()}
        meta = (f"status={resp.status} CL={h.get('content-length')} "
                f"TE={h.get('transfer-encoding')} CE={h.get('content-encoding')} conn={h.get('connection')}")
        try:
            data = resp.read()
            print(f"[DIAG2] {label} OK len={len(data)} {meta}", flush=True)
        except http.client.IncompleteRead as e:
            print(f"[DIAG2] {label} INCOMPLETE partial={len(e.partial)} {meta} "
                  f"tail={e.partial[-100:]!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[DIAG2] {label} ERR={type(e).__name__}:{e!r}", flush=True)


def main():
    # Get real item refs from the activity that was failing, then fetch them two ways.
    refs = []
    try:
        act = air._gateway_post(
            "/learnosity/v2/data/activities/",
            {"activity_references": ["US-G6-Identify-Patterns-and-Parts-of-Algebraic-Expressions-V3-1"],
             "with_items": True},
        )
        for a in (act or []):
            items = (a.get("data", {}) or {}).get("items") or a.get("items") or []
            for it in items:
                r = it if isinstance(it, str) else (it.get("reference") or it.get("id"))
                if r:
                    refs.append(r)
        print(f"[DIAG2] activity_item_refs n={len(refs)} sample={refs[:3]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[DIAG2] activity_lookup_err={type(e).__name__}:{e!r}", flush=True)

    payload = {"request_data": {"references": refs, "limit": 50}} if refs else {"request_data": {"limit": 50}}
    _call("http11_v4", air._IPV4_OPENER, payload)
    _call("http10_v4", _mk_opener(True), payload)


main()
