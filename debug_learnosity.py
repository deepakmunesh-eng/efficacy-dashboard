"""Standalone Learnosity gateway debug tool.

Reads Learnosity item content through the Cuemath data gateway using ONLY the
credentials in .env:

    POST {DATA_GATEWAY_BASE_URL}
    Authorization: Bearer {DATA_GATEWAY_TOKEN}
    Content-Type: application/json

No Michelangelo / curriculum-studio hop — this talks straight to the gateway.

It prints:
  1. This machine's public IPv4 egress IP (what the gateway's allowlist sees)
  2. The raw gateway response: HTTP status + body

The gateway enforces an IP allowlist, so a non-whitelisted source gets
    401 {"message":"IP not whitelisted"}
even with a valid token. Compare the egress IP printed below against the IPs
your admin whitelisted — if they differ, that's the bug.

Run:  python debug_learnosity.py [ITEM_REF ...]
"""
from __future__ import annotations

import http.client
import json
import socket
import sys
import urllib.error
import urllib.request

from config.settings import (
    DATA_GATEWAY_BASE_URL,
    DATA_GATEWAY_TOKEN,
    LEARNOSITY_MS_DOMAIN_URL,
)


# ── Force IPv4 (the whitelisted Railway static egress IP is IPv4) ───────────────
class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        af, socktype, proto, _canon, sa = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )[0]
        sock = socket.socket(af, socktype, proto)
        if self.timeout is not None and self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(self.timeout)
        sock.connect(sa)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req)


_IPV4_OPENER = urllib.request.build_opener(_IPv4HTTPSHandler())


def _egress_ip() -> str:
    """The public IPv4 the gateway's allowlist actually sees for our requests."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://ipv4.icanhazip.com"):
        try:
            with _IPV4_OPENER.open(url, timeout=10) as resp:
                return resp.read().decode().strip()
        except Exception as exc:  # noqa: BLE001
            print(f"  (ip lookup via {url} failed: {exc})")
    return "UNKNOWN"


def _gateway_read(path: str, payload: dict):
    body = json.dumps({
        "service": "LEARNOSITY",
        "path":    path,
        "method":  "POST",
        "payload": {"domain_url": LEARNOSITY_MS_DOMAIN_URL, **payload},
    }).encode("utf-8")
    req = urllib.request.Request(DATA_GATEWAY_BASE_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {DATA_GATEWAY_TOKEN}")
    req.add_header("Content-Type", "application/json")
    with _IPV4_OPENER.open(req, timeout=25) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def main() -> None:
    print("=" * 70)
    print("Learnosity gateway debug")
    print("=" * 70)
    print(f"DATA_GATEWAY_BASE_URL : {DATA_GATEWAY_BASE_URL or '(missing!)'}")
    print(f"DATA_GATEWAY_TOKEN    : {'set (' + str(len(DATA_GATEWAY_TOKEN)) + ' chars)' if DATA_GATEWAY_TOKEN else '(missing!)'}")
    print(f"LEARNOSITY_MS_DOMAIN  : {LEARNOSITY_MS_DOMAIN_URL}")

    if not (DATA_GATEWAY_BASE_URL and DATA_GATEWAY_TOKEN):
        print("\nERROR: gateway not configured — set DATA_GATEWAY_BASE_URL and "
              "DATA_GATEWAY_TOKEN in .env")
        sys.exit(1)

    print("\nThis machine's public IPv4 (what the allowlist checks):")
    print(f"  --> {_egress_ip()}")

    refs = sys.argv[1:] or []
    payload = ({"request_data": {"references": refs, "limit": 50}} if refs
               else {"request_data": {"limit": 5}})
    print(f"\nCalling POST {DATA_GATEWAY_BASE_URL}")
    print(f"  path=/learnosity/v2/items/  refs={refs or '(none — first 5)'}")

    try:
        status, text = _gateway_read("/learnosity/v2/items/", payload)
        print(f"\nHTTP {status}")
        print(text[:1500])
        print("\n[OK] Success -- gateway accepted the request from this IP.")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"\n[FAIL] HTTP {exc.code}: {detail[:500]}")
        if exc.code == 401 and "whitelist" in detail.lower():
            print("\n>>> This is the IP-allowlist rejection. The IP printed above is "
                  "NOT on the gateway allowlist. Whitelist THAT exact IPv4 address.")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
