"""Shared agent-tools.cloud accounts: hub identity, ownership and review status.

Run: python tests/test_shared_accounts.py   (throwaway databases only)
"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import tempfile
import time

from cryptography.fernet import Fernet

TMP = tempfile.mkdtemp()
HUB_DB = os.path.join(TMP, "hub.db")
MAIN_DB = os.path.join(TMP, "main.db")
SECRET = "test-secret-not-production"
os.environ.update({
    "DB_PATH": HUB_DB, "FERNET_KEY": Fernet.generate_key().decode(),
    "ADMIN_TOKEN": "admin-test", "SESSION_SECRET": SECRET,
    "DIRECTORY_DB_PATH": MAIN_DB, "FACILITATOR": "payai",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with sqlite3.connect(MAIN_DB) as c:
    c.executescript("""
    CREATE TABLE users (id INTEGER PRIMARY KEY, provider TEXT, provider_uid TEXT,
      login TEXT, avatar_url TEXT, email TEXT, email_verified INTEGER DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'active', created_at INTEGER, last_login_at INTEGER);
    CREATE TABLE api_keys (id INTEGER PRIMARY KEY, user_id INTEGER, key_hash TEXT,
      revoked_at INTEGER);
    INSERT INTO users(id, provider, provider_uid, login, email, status, created_at)
      VALUES (1,'github','1','alice','alice@example.invalid','active',0),
             (2,'github','2','bob',NULL,'active',0),
             (3,'github','3','mallory',NULL,'blocked',0);
    """)
    KEY = "atc_live_testkeyvalue"
    c.execute("INSERT INTO api_keys(user_id,key_hash) VALUES (2,?)",
              (hashlib.sha256(KEY.encode()).hexdigest(),))
    REVOKED = "atc_live_revokedvalue"
    c.execute("INSERT INTO api_keys(user_id,key_hash,revoked_at) VALUES (2,?,1)",
              (hashlib.sha256(REVOKED.encode()).hexdigest(),))


def token(payload, secret=SECRET, ttl=3600):
    body = json.dumps({**payload, "exp": int(time.time()) + ttl},
                      separators=(",", ":")).encode()
    b = base64.urlsafe_b64encode(body).decode().rstrip("=")
    return "%s.%s" % (b, hmac.new(secret.encode(), b.encode(), hashlib.sha256).hexdigest())


from hub import safety  # noqa: E402
safety.upstream_host_reason = lambda url: None
from hub import sellers  # noqa: E402


async def _no_probe(*a, **k):
    return {"reachable": True, "http_status": 200, "latency_ms": 1, "error": None}
sellers.probe_upstream = _no_probe

from fastapi.testclient import TestClient  # noqa: E402
from hub.main import app  # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  ok   %-62s %s" % (label, extra))
    else:
        fail += 1
        print("  FAIL %-62s %s" % (label, extra))


AUD = "hub.agent-tools.cloud"
ALICE = {"atc_hub": token({"uid": 1, "aud": AUD})}
WALLET = "0x" + "1" * 40


def body(slug):
    return {"service_slug": slug, "payout_address": WALLET,
            "upstream_base_url": "https://api.example.com", "price_usdc": 0.01}


with TestClient(app) as c:
    check("anonymous identity is signed out",
          c.get("/api/v1/me").json().get("signed_in") is False)
    r = c.post("/api/v1/submit", json=body("anon-api"))
    check("anonymous submit is refused with a sign-in link",
          r.status_code == 401 and "auth/hub" in r.json()["detail"]["sign_in_url"])
    for label, cookie in (
            ("main-site session (no audience) is not a hub identity", token({"uid": 1})),
            ("wrong audience is refused", token({"uid": 1, "aud": "other"})),
            ("wrong secret is refused", token({"uid": 1, "aud": AUD}, secret="x")),
            ("expired hub credential is refused", token({"uid": 1, "aud": AUD}, ttl=-5)),
            ("blocked account is refused", token({"uid": 3, "aud": AUD}))):
        check(label, c.get("/api/v1/me", cookies={"atc_hub": cookie}).json()["signed_in"] is False)

    me = c.get("/api/v1/me", cookies=ALICE).json()
    check("hub cookie resolves the main-site account",
          me.get("signed_in") and me.get("login") == "alice")
    r = c.post("/api/v1/submit", json=body("alice-api"), cookies=ALICE)
    check("signed-in submit succeeds", r.status_code == 200 and r.json()["status"] == "pending")
    with sqlite3.connect(HUB_DB) as h:
        acct, email = h.execute("SELECT account_id, contact_email FROM sellers "
                                "WHERE slug='alice-api-owner'").fetchone()
    check("seller is bound to the account id", acct == 1)
    check("contact email defaults to the verified account email",
          email == "alice@example.invalid")

    bob = {"Authorization": "Bearer " + KEY}
    check("main-site API key identifies the account",
          c.get("/api/v1/me", headers=bob).json().get("login") == "bob")
    check("revoked API key is refused", c.get(
        "/api/v1/me", headers={"Authorization": "Bearer " + REVOKED}).json()["signed_in"] is False)
    check("API-key submit succeeds", c.post(
        "/api/v1/submit", json=body("bob-api"), headers=bob).status_code == 200)
    check("another account cannot reuse a taken slug", c.post(
        "/api/v1/submit", json=body("alice-api"), headers=bob).status_code == 409)

    mine = c.get("/api/v1/my/services", cookies=ALICE).json()
    check("My services lists only own submissions",
          [s["slug"] for s in mine] == ["alice-api"] and mine[0]["status"] == "pending")
    check("My services never exposes secrets",
          not any(k in mine[0] for k in ("proxy_secret", "upstream_auth_enc")))
    check("My services requires sign-in", c.get("/api/v1/my/services").status_code == 401)

    admin = {"Authorization": "Bearer admin-test"}
    r = c.post("/api/v1/admin/reject", headers=admin,
               json={"service_slug": "alice-api", "note": "Upstream already charges x402"})
    check("admin reject stores a reason", r.status_code == 200 and r.json()["note"])
    mine = c.get("/api/v1/my/services", cookies=ALICE).json()
    check("seller sees rejected status and reason",
          mine[0]["status"] == "rejected" and mine[0]["review_note"] == "Upstream already charges x402")
    check("non-admin cannot reject", c.post("/api/v1/admin/reject", cookies=ALICE,
          json={"service_slug": "bob-api"}).status_code == 401)

    page = c.get("/my", cookies=ALICE)
    check("My services page is private", page.status_code == 200
          and page.headers.get("cache-control") == "private, no-store")
    check("list page carries the sign-in gate", 'id="signInGate"' in c.get("/list").text)

with sqlite3.connect(HUB_DB) as h:
    legacy = h.execute("SELECT COUNT(*) FROM sellers WHERE account_id IS NULL").fetchone()[0]
    cols = {r[1] for r in h.execute("PRAGMA table_info(services)")}
check("migration adds review columns", {"review_note", "reviewed_at"} <= cols)
check("no seller row is left without an account in this run", legacy == 0)

print("\n%d passed, %d failed" % (ok, fail))
raise SystemExit(1 if fail else 0)
