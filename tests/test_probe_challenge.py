"""GET/HEAD probes on POST-only services get the 402 challenge, paid calls stay POST-only.

Run: python tests/test_probe_challenge.py   (throwaway databases only)
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
          "require_json": True, "fixed_model": "M", "allow_stream": False}
URL = "/gw/probe-svc/v1/chat/completions"

with TestClient(app) as c:
    with sqlite3.connect(HUB_DB) as db:
        db.execute("INSERT INTO sellers(id,slug,payout_address,created_at) VALUES (1,'probe',?,?)",
                   ("0x" + "1" * 40, int(time.time())))
        db.execute(
            "INSERT INTO services(seller_id,slug,upstream_base_url,proxy_secret,price_usdc,"
            "created_at,status,request_policy_json) VALUES (1,'probe-svc','https://upstream.invalid',"
            "'s',0.01,?,'live',?)", (int(time.time()), json.dumps(POLICY)))

    for m in ("GET", "HEAD"):
        r = c.request(m, URL)
        check(f"{m} probe answers 402", r.status_code == 402, r.status_code)
        hdr = r.headers.get("payment-required")
        check(f"{m} probe carries PAYMENT-REQUIRED header", bool(hdr))
        if hdr:
            ch = json.loads(base64.b64decode(hdr))
            check(f"{m} challenge advertises POST",
                  ch["extensions"]["bazaar"]["info"]["method"] == "POST")
            check(f"{m} challenge names the resource",
                  ch["resource"]["url"].endswith(URL))

    r = c.get("/gw/probe-svc/v1/models")
    check("GET probe on undeclared path stays 404", r.status_code == 404, r.status_code)
    r = c.get(URL, headers={"PAYMENT-SIGNATURE": base64.b64encode(b"{}").decode()})
    check("GET with payment header is still refused (405)", r.status_code == 405, r.status_code)
    r = c.post(URL, json={"messages": [{"role": "user", "content": "hi"}]})
    check("POST without payment answers 402", r.status_code == 402, r.status_code)
    hdr = r.headers.get("payment-required")
    check("POST challenge advertises POST",
          bool(hdr) and json.loads(base64.b64decode(hdr))["extensions"]["bazaar"]["info"]["method"] == "POST")
    r = c.post(URL, json={"model": "other", "messages": []})
    check("POST policy violation still rejected before payment", r.status_code == 422, r.status_code)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
