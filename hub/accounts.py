"""Identity from the agent-tools.cloud account system.

The hub keeps no users of its own. A visitor is identified by either the
`atc_hub` cookie the main site issues (HMAC, hub audience) or a main-site API
key; both resolve to a row in the main site's users table, opened read-only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time

from fastapi import Request

HUB_COOKIE = "atc_hub"
HUB_AUDIENCE = "hub.agent-tools.cloud"
API_KEY_PREFIX = "atc_live_"


def _unsign(value: str | None, secret: str) -> dict | None:
    if not value or not secret or "." not in value:
        return None
    b, _, sig = value.rpartition(".")
    expected = hmac.new(secret.encode("utf-8"), b.encode("ascii"),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
    except Exception:
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < time.time():
        return None
    if data.get("aud") != HUB_AUDIENCE:
        return None
    return data


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _user_by_id(path: str, uid: int) -> dict | None:
    with _connect(path) as conn:
        row = conn.execute("SELECT id, login, avatar_url, email, status "
                           "FROM users WHERE id=?", (uid,)).fetchone()
    if row is None or row["status"] != "active":
        return None
    return {"id": row["id"], "login": row["login"],
            "avatar_url": row["avatar_url"], "email": row["email"]}


def _uid_from_key(path: str, raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw.startswith(API_KEY_PREFIX):
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with _connect(path) as conn:
        row = conn.execute("SELECT user_id FROM api_keys WHERE key_hash=? "
                           "AND revoked_at IS NULL", (digest,)).fetchone()
    return int(row["user_id"]) if row else None


def current_user(request: Request) -> dict | None:
    """The signed-in main-site account, or None. Fails closed on any error."""
    settings = request.app.state.settings
    path = settings.directory_db_path
    if not path:
        return None
    try:
        data = _unsign(request.cookies.get(HUB_COOKIE), settings.session_secret)
        uid = int(data["uid"]) if data and data.get("uid") else None
        if uid is None:
            scheme, _, raw = (request.headers.get("authorization") or "").partition(" ")
            if scheme.lower() == "bearer":
                uid = _uid_from_key(path, raw)
        return _user_by_id(path, uid) if uid else None
    except Exception:
        return None
