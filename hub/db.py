"""SQLite store for sellers, hosted services, and per-call usage.

Append-only usage log; sellers/services are mutable rows. The hub never holds
funds — money settles straight to each seller's payTo via the facilitator — so
there is no balance/ledger table here, only metering + audit.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path
from threading import Lock

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    slug           TEXT UNIQUE NOT NULL,
    name           TEXT,
    contact_email  TEXT,
    payout_address TEXT NOT NULL,
    payout_network TEXT NOT NULL DEFAULT 'eip155:8453',
    created_at     INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS services (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id           INTEGER NOT NULL REFERENCES sellers(id),
    slug                TEXT UNIQUE NOT NULL,
    upstream_base_url   TEXT NOT NULL,
    upstream_auth_header TEXT,           -- header name to inject (e.g. Authorization)
    upstream_auth_enc   TEXT,            -- Fernet-encrypted header value (seller's key)
    proxy_secret        TEXT NOT NULL,   -- injected as X-Hub-Secret; seller verifies it
    price_usdc          REAL NOT NULL,   -- per-call price in USDC
    description         TEXT,
    category            TEXT,
    health              TEXT DEFAULT 'unknown',
    created_at          INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'   -- pending|live|paused|rejected
);
CREATE INDEX IF NOT EXISTS idx_services_slug ON services(slug);
CREATE INDEX IF NOT EXISTS idx_services_status ON services(status);

CREATE TABLE IF NOT EXISTS usage_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            INTEGER NOT NULL,
    service_id    INTEGER NOT NULL,
    path          TEXT,
    method        TEXT,
    http_status   INTEGER,
    paid          INTEGER NOT NULL DEFAULT 0,
    payer         TEXT,
    amount_atomic TEXT,
    tx_hash       TEXT,
    latency_ms    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log(ts);
CREATE INDEX IF NOT EXISTS idx_usage_service ON usage_log(service_id);

CREATE TABLE IF NOT EXISTS needs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    INTEGER NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    category      TEXT,
    budget_usd    REAL,
    contact       TEXT,
    status        TEXT NOT NULL DEFAULT 'open'   -- open|fulfilled|closed
);
CREATE INDEX IF NOT EXISTS idx_needs_created ON needs(created_at);
CREATE INDEX IF NOT EXISTS idx_needs_status ON needs(status);
"""


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class DB:
    def __init__(self, path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = _row_to_dict
        self._conn.executescript(_SCHEMA)

    # --- sellers ---
    def create_seller(self, *, slug: str, name: str | None, contact_email: str | None,
                      payout_address: str, payout_network: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sellers(slug,name,contact_email,payout_address,payout_network,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (slug, name, contact_email, payout_address, payout_network, int(time.time())),
            )
            return int(cur.lastrowid)

    def get_seller(self, slug: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM sellers WHERE slug=?", (slug,))
            return cur.fetchone()

    # --- services ---
    def create_service(self, *, seller_id: int, slug: str, upstream_base_url: str,
                       upstream_auth_header: str | None, upstream_auth_enc: str | None,
                       price_usdc: float, description: str | None,
                       category: str | None) -> tuple[int, str]:
        proxy_secret = secrets.token_urlsafe(24)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO services(seller_id,slug,upstream_base_url,upstream_auth_header,"
                "upstream_auth_enc,proxy_secret,price_usdc,description,category,created_at,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'pending')",
                (seller_id, slug, upstream_base_url, upstream_auth_header, upstream_auth_enc,
                 proxy_secret, price_usdc, description, category, int(time.time())),
            )
            return int(cur.lastrowid), proxy_secret

    def get_service(self, slug: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM services WHERE slug=?", (slug,))
            return cur.fetchone()

    def set_service_status(self, slug: str, status: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE services SET status=? WHERE slug=?", (status, slug))

    def set_service_health(self, slug: str, health: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE services SET health=? WHERE slug=?", (health, slug))

    def list_services(self, status: str | None = None) -> list[dict]:
        with self._lock:
            if status:
                cur = self._conn.execute(
                    "SELECT s.*, se.payout_address, se.payout_network FROM services s "
                    "JOIN sellers se ON se.id=s.seller_id WHERE s.status=? ORDER BY s.created_at DESC",
                    (status,),
                )
            else:
                cur = self._conn.execute(
                    "SELECT s.*, se.payout_address, se.payout_network FROM services s "
                    "JOIN sellers se ON se.id=s.seller_id ORDER BY s.created_at DESC"
                )
            return cur.fetchall()

    def service_with_payout(self, slug: str) -> dict | None:
        """Service row joined with seller payout address (for building the 402 challenge)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT s.*, se.payout_address, se.payout_network FROM services s "
                "JOIN sellers se ON se.id=s.seller_id WHERE s.slug=?",
                (slug,),
            )
            return cur.fetchone()

    # --- usage ---
    def log_usage(self, *, service_id: int, path: str, method: str, http_status: int,
                  paid: bool, payer: str | None, amount_atomic: str | None,
                  tx_hash: str | None, latency_ms: int | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage_log(ts,service_id,path,method,http_status,paid,payer,"
                "amount_atomic,tx_hash,latency_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(time.time()), service_id, path, method, http_status,
                 1 if paid else 0, payer, amount_atomic, tx_hash, latency_ms),
            )

    def stats_24h(self) -> dict:
        cutoff = int(time.time()) - 86_400
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(paid),0) AS paid_calls "
                "FROM usage_log WHERE ts>=?",
                (cutoff,),
            )
            row = cur.fetchone()
            cur = self._conn.execute("SELECT COUNT(*) AS n FROM services WHERE status='live'")
            live = cur.fetchone()["n"]
            cur = self._conn.execute("SELECT COUNT(*) AS n FROM needs WHERE status='open'")
            open_needs = cur.fetchone()["n"]
        return {
            "window_seconds": 86_400,
            "calls_24h": row["calls"],
            "paid_calls_24h": row["paid_calls"],
            "live_services": live,
            "open_needs": open_needs,
        }

    # --- needs (demand side) ---
    def create_need(self, *, title: str, description: str | None, category: str | None,
                    budget_usd: float | None, contact: str | None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO needs(created_at,title,description,category,budget_usd,contact) "
                "VALUES (?,?,?,?,?,?)",
                (int(time.time()), title, description, category, budget_usd, contact),
            )
            return int(cur.lastrowid)

    def list_needs(self, status: str = "open", limit: int = 100) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id,created_at,title,description,category,budget_usd,status "
                "FROM needs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
            return cur.fetchall()

    def open_needs_count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) AS n FROM needs WHERE status='open'")
            return cur.fetchone()["n"]


    def close(self) -> None:
        with self._lock:
            self._conn.close()
