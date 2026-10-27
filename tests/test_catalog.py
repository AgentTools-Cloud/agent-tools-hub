"""Buyer-facing catalog: /.well-known/x402, /llms.txt, /v1/models, rich 402, detail page.

Run: python tests/test_catalog.py   (throwaway databases only)
"""
import base64
import json
import os
import sqlite3
import sys
import tempfile
import time

from cryptography.fernet import Fernet

TMP = tempfile.mkdtemp()
HUB_DB = os.path.join(TMP, "hub.db")
os.environ.update({
    "DB_PATH": HUB_DB, "FERNET_KEY": Fernet.generate_key().decode(),
    "ADMIN_TOKEN": "admin-test", "SESSION_SECRET": "test-secret-not-production",
    "DIRECTORY_DB_PATH": os.path.join(TMP, "main.db"), "FACILITATOR": "payai",
    "PUBLIC_URL": "https://hub.example",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from hub.main import app  # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print("  %s %-60s %s" % ("ok  " if cond else "FAIL", label, extra))


POLICY = {"allowed_methods": ["POST"], "allowed_paths": ["v1/chat/completions"],
          "require_json": True, "fixed_model": "Model-X", "upstream_model": "org/model-x",
          "allow_stream": False, "max_output_tokens": 4096, "sanitize_response": True}
URL = "https://hub.example/gw/chat-svc/v1/chat/completions"

with TestClient(app) as c:
    with sqlite3.connect(HUB_DB) as db:
        now = int(time.time())
        db.execute("INSERT INTO sellers(id,slug,payout_address,created_at) VALUES (1,'s',?,?)",
                   ("0x" + "1" * 40, now))
        db.execute(
            "INSERT INTO services(seller_id,slug,upstream_base_url,proxy_secret,price_usdc,"
            "created_at,status,request_policy_json,description,category) VALUES "
            "(1,'chat-svc','https://upstream.invalid','s',0.01,?,'live',?,'Chat <b>model</b>','AI/LLM')",
            (now, json.dumps(POLICY)))
        db.execute(
            "INSERT INTO services(seller_id,slug,upstream_base_url,proxy_secret,price_usdc,"
            "created_at,status) VALUES (1,'hidden-svc','https://upstream.invalid','s',0.01,?,'pending')",
            (now,))

    r = c.get("/.well-known/x402")
    check("well-known 200", r.status_code == 200, r.status_code)
    doc = r.json()
    res = doc.get("resources") or []
    check("well-known lists only live services", len(res) == 1, len(res))
    e = res[0] if res else {}
    check("resource is the exact chat URL", e.get("resource") == URL, e.get("resource"))
    check("method POST with empty probe_body", e.get("method") == "POST" and e.get("probe_body") == {})
    check("accepts carries amount + payTo",
          e.get("accepts", [{}])[0].get("amount") == "10000"
          and e["accepts"][0].get("payTo") == "0x" + "1" * 40)
    check("input example uses fixed model", e.get("input_example", {}).get("model") == "Model-X")
    check("schema caps max_tokens",
          e.get("input_schema", {}).get("properties", {}).get("max_tokens", {}).get("maximum") == 4096)
    check("upstream model not leaked", "org/model-x" not in r.text)
    check("upstream URL not leaked", "upstream.invalid" not in r.text)
    check("x402.json alias", c.get("/.well-known/x402.json").json() == doc)

    r = c.get("/v1/models")
    ids = [m["id"] for m in r.json().get("data", [])]
    check("/v1/models lists fixed model", ids == ["Model-X"], ids)
    check("/v1/models gives endpoint", r.json()["data"][0]["x402"]["endpoint"] == URL)

    r = c.get("/llms.txt")
    check("llms.txt 200 text", r.status_code == 200 and r.headers["content-type"].startswith("text/plain"))
    check("llms.txt names endpoint and limits",
          f"POST {URL}" in r.text and "4096" in r.text and "Model-X" in r.text)
    check("llms.txt says failed calls free", "not charged" in r.text)
    check("llms.txt omits pending service", "hidden-svc" not in r.text)

    r = c.post("/gw/chat-svc/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    ch = json.loads(base64.b64decode(r.headers["payment-required"]))
    info = ch["extensions"]["bazaar"]["info"]
    check("402 bazaar path is exact", info["path"] == "/gw/chat-svc/v1/chat/completions", info["path"])
    check("402 bazaar has input example", info.get("input", {}).get("body", {}).get("model") == "Model-X")
    check("402 bazaar has output example", "choices" in info.get("output", {}).get("example", {}))
    check("402 bazaar limits", info.get("limits", {}).get("stream") is False)
    check("402 schema requires messages",
          ch["extensions"]["bazaar"]["schema"].get("required") == ["messages"])

    r = c.get("/services/chat-svc")
    check("detail page server-rendered", r.status_code == 200 and "Loading" not in r.text)
    check("detail shows endpoint + limits", URL in r.text and "4096" in r.text and "Model-X" in r.text)
    check("detail has node + python snippets",
          "wrapFetchWithPayment" in r.text and "x402HttpxClient" in r.text)
    check("detail escapes description", "Chat &lt;b&gt;model&lt;/b&gt;" in r.text)
    check("detail does not leak upstream", "upstream.invalid" not in r.text and "org/model-x" not in r.text)
    check("pending service detail 404", c.get("/services/hidden-svc").status_code == 404)
    check("unknown detail 404", c.get("/services/nope").status_code == 404)

    r = c.get("/about")
    check("about describes settle-after-upstream", "pays nothing" in r.text and "POST /gw/" in r.text)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
