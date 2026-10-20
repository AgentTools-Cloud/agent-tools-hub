"""Seller-URL probes must only ever connect to public addresses.

Run: python tests/test_public_http.py   (no real network)
"""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hub import public_http, safety, sellers  # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print("  %s %-60s %s" % ("ok  " if cond else "FAIL", label, extra))


def unsafe(url):
    try:
        public_http.parse_url(url)
    except public_http.UnsafeURL:
        return True
    return False


for url in ("http://127.0.0.1/", "http://10.0.0.5/", "http://169.254.169.254/latest",
            "http://[::1]/", "http://localhost/", "http://svc.internal/", "ftp://a.com/",
            "http://user:pw@api.example.com/", "http://100.64.0.1/"):
    check("reject %s" % url, unsafe(url))
for url in ("https://api.example.com/v1", "http://99.81.245.60/tokenscan"):
    check("allow %s" % url, not unsafe(url))

seen = []


class Recorder(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        seen.append((request.url.host, request.headers.get("host")))
        return httpx.Response(200, text="ok")


async def fetch(url, resolver):
    async with httpx.AsyncClient(transport=public_http.PublicAsyncTransport(
            resolver=resolver, inner=Recorder())) as c:
        return await c.get(url)


r = asyncio.run(fetch("https://api.example.com/x", lambda h, p: ["93.184.216.34"]))
check("public name is pinned to its resolved IP", r.status_code == 200
      and seen[-1] == ("93.184.216.34", "api.example.com"), str(seen[-1]))


def rebinding(host, port):
    return ["93.184.216.34", "10.0.0.1"]


try:
    asyncio.run(fetch("https://api.example.com/x", rebinding))
    check("name resolving to any private IP is refused", False)
except public_http.UnsafeURL:
    check("name resolving to any private IP is refused", True)


# probe_upstream end to end: the old guard passes, the transport still blocks.
safety.upstream_host_reason = lambda url: None
orig = public_http.resolve_public
public_http.resolve_public = lambda h, p: (_ for _ in ()).throw(
    public_http.UnsafeURL("URL host resolves to a non-public address"))
res = asyncio.run(sellers.probe_upstream("https://rebind.example.net/"))
check("probe_upstream reports blocked instead of connecting",
      res["reachable"] is False and "blocked" in (res["error"] or ""), res["error"])
res = asyncio.run(sellers.probe_upstream("http://127.0.0.1:9300/"))
check("probe_upstream blocks loopback even if legacy guard is bypassed",
      res["reachable"] is False and "blocked" in (res["error"] or ""), res["error"])
public_http.resolve_public = orig

print("\n%d passed, %d failed" % (ok, fail))
raise SystemExit(1 if fail else 0)
