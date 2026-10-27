"""Paid calls settle only after the upstream succeeds; failures never charge.

Run: python tests/test_settle_after_upstream.py   (throwaway databases only)
"""
import base64
import json
import os
import sqlite3
import sys
import tempfile
import time

import httpx
from cryptography.fernet import Fernet

TMP = tempfile.mkdtemp()
HUB_DB = os.path.join(TMP, "hub.db")
os.environ.update({
    "DB_PATH": HUB_DB, "FERNET_KEY": Fernet.generate_key().decode(),
    "ADMIN_TOKEN": "admin-test", "SESSION_SECRET": "test-secret-not-production",
    "DIRECTORY_DB_PATH": os.path.join(TMP, "main.db"), "FACILITATOR": "payai",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hub import safety  # noqa: E402
safety.upstream_host_reason = lambda url: None
from fastapi.testclient import TestClient  # noqa: E402
from hub.main import app  # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print("  %s %-62s %s" % ("ok  " if cond else "FAIL", label, extra))


class FakeFacilitator:
    def __init__(self):
        self.valid = True
        self.settle_ok = True
        self.verified = 0
        self.settled = 0

    async def verify(self, *, payment_payload, payment_requirements):
        self.verified += 1
        return {"isValid": self.valid, "payer": "0xbuyer",
                **({} if self.valid else {"invalidReason": "insufficient_funds"})}

    async def settle(self, *, payment_payload, payment_requirements):
        self.settled += 1
        if not self.settle_ok:
            return {"success": False, "errorReason": "nonce_used"}
        return {"success": True, "payer": "0xbuyer", "transaction": f"0xtx{self.settled}"}


FAC = FakeFacilitator()
UPSTREAM = {"mode": "ok", "calls": 0}


def upstream_handler(request: httpx.Request) -> httpx.Response:
    UPSTREAM["calls"] += 1
    mode = UPSTREAM["mode"]
    if mode == "502":
        return httpx.Response(502, json={"error": "boom"})
    if mode == "garbage":
        return httpx.Response(200, content=b"\x8b\x00not-json")
    if mode == "timeout":
        raise httpx.ReadTimeout("slow", request=request)
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "model": "up",
                                     "choices": [{"index": 0, "message": {"role": "assistant",
                                                                          "content": "hi"}}],
                                     "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                               "total_tokens": 2}})


def payment(nonce):
    body = {"x402Version": 2, "payload": {"signature": "0xsig",
                                          "authorization": {"from": "0xBuyer", "nonce": nonce}}}
    return {"PAYMENT-SIGNATURE": base64.b64encode(json.dumps(body).encode()).decode()}


POLICY = {"allowed_methods": ["POST"], "allowed_paths": ["v1/chat/completions"],
          "require_json": True, "fixed_model": "M", "allow_stream": False,
          "sanitize_response": True}
URL = "/gw/paid-svc/v1/chat/completions"
REQ = {"messages": [{"role": "user", "content": "hi"}]}


def usage():
    with sqlite3.connect(HUB_DB) as db:
        return db.execute("SELECT http_status,paid,amount_atomic,tx_hash FROM usage_log "
                          "ORDER BY id DESC LIMIT 1").fetchone()


with TestClient(app) as c:
    app.state.facilitator_pool.client = lambda backend: FAC
    app.state.proxy_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler))
    with sqlite3.connect(HUB_DB) as db:
        db.execute("INSERT INTO sellers(id,slug,payout_address,created_at) VALUES (1,'s',?,?)",
                   ("0x" + "1" * 40, int(time.time())))
        db.execute(
            "INSERT INTO services(seller_id,slug,upstream_base_url,proxy_secret,price_usdc,"
            "created_at,status,request_policy_json) VALUES (1,'paid-svc','https://upstream.test',"
            "'s',0.01,?,'live',?)", (int(time.time()), json.dumps(POLICY)))

    r = c.post(URL, json=REQ, headers=payment("0x01"))
    check("upstream 200 -> response 200", r.status_code == 200, r.status_code)
    check("upstream 200 -> settled once", FAC.settled == 1, FAC.settled)
    check("success carries PAYMENT-RESPONSE", bool(r.headers.get("payment-response")))
    check("success logged as paid with tx", usage()[1] == 1 and usage()[3] == "0xtx1", usage())

    for mode, label in (("502", "upstream 502"), ("garbage", "undecodable upstream body"),
                        ("timeout", "upstream timeout")):
        before = FAC.settled
        UPSTREAM["mode"] = mode
        r = c.post(URL, json=REQ, headers=payment(f"0x{mode}"))
        check(f"{label} -> client sees failure", r.status_code >= 500, r.status_code)
        check(f"{label} -> NOT settled", FAC.settled == before, FAC.settled)
        check(f"{label} -> logged unpaid", usage()[1] == 0 and usage()[2] == "0", usage())
        check(f"{label} -> no PAYMENT-RESPONSE", not r.headers.get("payment-response"))

    UPSTREAM["mode"] = "ok"
    r = c.post(URL, json=REQ, headers=payment("0x502"))
    check("authorization unused by a failed call can be retried", r.status_code == 200, r.status_code)

    calls = UPSTREAM["calls"]
    r = c.post(URL, json=REQ, headers=payment("0x01"))
    check("already-settled authorization is refused (402)", r.status_code == 402, r.status_code)
    check("refused replay never reaches upstream", UPSTREAM["calls"] == calls)

    FAC.valid = False
    calls, settled = UPSTREAM["calls"], FAC.settled
    r = c.post(URL, json=REQ, headers=payment("0x99"))
    check("invalid payment -> 402 before upstream", r.status_code == 402 and UPSTREAM["calls"] == calls,
          r.status_code)
    check("invalid payment -> not settled", FAC.settled == settled)
    FAC.valid = True

    FAC.settle_ok = False
    r = c.post(URL, json=REQ, headers=payment("0x77"))
    check("settle failure after upstream -> 402, no content leaked",
          r.status_code == 402 and "choices" not in r.text, r.status_code)
    check("settle failure -> logged unpaid", usage()[1] == 0, usage())
    FAC.settle_ok = True

    r = c.post(URL, json=REQ)
    check("no payment header -> 402 challenge", r.status_code == 402 and bool(r.headers.get("payment-required")))

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
