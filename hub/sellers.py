"""Seller self-serve onboarding + admin approval.

Public:
  POST /api/v1/submit         -> register seller + service (status=pending)
Admin (Bearer ADMIN_TOKEN):
  POST /api/v1/admin/approve  -> probe upstream, set status=live, mirror to directory
  POST /api/v1/admin/reject
  GET  /api/v1/admin/services -> list (any status)
Public:
  GET  /api/v1/services       -> list live services (no secrets)
  GET  /api/v1/services/{slug}-> one live service (no secrets)
"""

from __future__ import annotations

import logging
import re
import time

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter()

from .config import (FACILITATOR_PRESETS, SELECTABLE_FACILITATORS,
                     facilitator_public, get_settings)
from . import safety

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

# fields we never expose publicly
_SECRET_FIELDS = {"upstream_auth_enc", "proxy_secret", "upstream_auth_header"}


class SubmitRequest(BaseModel):
    service_slug: str = Field(min_length=3, max_length=40)
    seller_name: str | None = None
    contact_email: str | None = None
    payout_address: str
    payout_network: str = "eip155:8453"
    facilitator: str | None = None  # backend id; defaults to hub default (payai)
    upstream_base_url: str
    upstream_auth_header: str | None = None
    upstream_auth_value: str | None = None  # plaintext; encrypted before storage
    price_usdc: float = Field(gt=0)
    description: str | None = None
    category: str | None = None


class NeedRequest(BaseModel):
    title: str = Field(min_length=4, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = None
    budget_usd: float | None = Field(default=None, ge=0)
    contact: str | None = Field(default=None, max_length=200)


async def probe_upstream(url: str, *, method: str = "GET",
                         auth_header: str | None = None,
                         auth_value: str | None = None,
                         path: str = "", timeout: float = 12.0) -> dict:
    """Actually call the seller's upstream and report whether it answered. SSRF
    guard runs first (we never probe internal/metadata hosts)."""
    target = url.rstrip("/") + (("/" + path.lstrip("/")) if path else "")
    reason = safety.upstream_host_reason(target)
    if reason:
        return {"reachable": False, "error": f"blocked: {reason}",
                "http_status": None, "latency_ms": None}
    headers = {"User-Agent": "agent-tools-hub/0.1 (+https://hub.agent-tools.cloud)"}
    if auth_header and auth_value:
        headers[auth_header] = auth_value
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=6.0, read=timeout, write=6.0, pool=6.0),
                follow_redirects=False) as c:
            r = await c.request(method, target, headers=headers)
        dt = int((time.monotonic() - t0) * 1000)
        return {"reachable": r.status_code < 500, "http_status": r.status_code,
                "latency_ms": dt, "error": None, "sample": (r.text or "")[:200]}
    except httpx.HTTPError as e:
        return {"reachable": False, "http_status": None,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "error": str(e)[:160]}


class TestRequest(BaseModel):
    upstream_base_url: str
    method: str = "GET"
    path: str | None = None
    upstream_auth_header: str | None = None
    upstream_auth_value: str | None = None


@router.post("/api/v1/test", tags=["sellers"])
async def test_upstream(req: TestRequest, request: Request) -> dict:
    """Dummy smoke test: hit a candidate upstream once and report reachability."""
    if not req.upstream_base_url.startswith(("http://", "https://")):
        raise HTTPException(422, "upstream_base_url must be http(s)")
    res = await probe_upstream(
        req.upstream_base_url, method=(req.method or "GET").upper(),
        auth_header=req.upstream_auth_header, auth_value=req.upstream_auth_value,
        path=req.path or "")
    res["target"] = req.upstream_base_url.rstrip("/") + (("/" + (req.path or "").lstrip("/")) if req.path else "")
    res["ok"] = bool(res.get("reachable"))
    res["message"] = ("Reached your endpoint." if res["ok"]
                      else "Could not reach your endpoint: " + (res.get("error") or "no 2xx/4xx response"))
    return res


def _public_view(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _SECRET_FIELDS}


def _require_admin(authorization: str | None, settings) -> None:
    expected = f"Bearer {settings.admin_token}"
    if not settings.admin_token or authorization != expected:
        raise HTTPException(status_code=401, detail="admin auth required")


@router.post("/api/v1/submit")
async def submit(req: SubmitRequest, request: Request) -> dict:
    db = request.app.state.db
    box = request.app.state.secret_box

    if not _SLUG_RE.match(req.service_slug):
        raise HTTPException(422, "slug must be lowercase alphanumeric/hyphen, 3-40 chars")
    if not _ADDR_RE.match(req.payout_address):
        raise HTTPException(422, "payout_address must be a 0x EVM address")
    fac = (req.facilitator or get_settings().facilitator).strip()
    if fac not in FACILITATOR_PRESETS:
        raise HTTPException(
            422, f"unknown facilitator '{fac}'; pick one of {SELECTABLE_FACILITATORS}")
    if not req.upstream_base_url.startswith(("http://", "https://")):
        raise HTTPException(422, "upstream_base_url must be http(s)")
    # SSRF guard: we will proxy to this URL, so refuse internal / cloud-metadata
    # targets. Re-checked per request in the gateway (DNS can change).
    _reason = safety.upstream_host_reason(req.upstream_base_url)
    if _reason:
        raise HTTPException(422, f"upstream not allowed: {_reason}")
    if db.get_service(req.service_slug) is not None:
        raise HTTPException(409, f"slug '{req.service_slug}' already taken")

    seller_slug = f"{req.service_slug}-owner"
    seller = db.get_seller(seller_slug)
    seller_id = seller["id"] if seller else db.create_seller(
        slug=seller_slug, name=req.seller_name, contact_email=req.contact_email,
        payout_address=req.payout_address, payout_network=req.payout_network,
    )

    enc = box.encrypt(req.upstream_auth_value) if req.upstream_auth_value else None
    service_id, proxy_secret = db.create_service(
        seller_id=seller_id, slug=req.service_slug, upstream_base_url=req.upstream_base_url,
        upstream_auth_header=req.upstream_auth_header, upstream_auth_enc=enc,
        price_usdc=req.price_usdc, description=req.description, category=req.category,
        facilitator=fac,
    )
    log.info("submit: service=%s id=%s status=pending", req.service_slug, service_id)
    smoke = await probe_upstream(
        req.upstream_base_url, method="GET",
        auth_header=req.upstream_auth_header, auth_value=req.upstream_auth_value)
    gw_url = f"{get_settings().public_url.rstrip('/')}/gw/{req.service_slug}"
    return {
        "status": "pending",
        "service_slug": req.service_slug,
        "gateway_url": gw_url,
        "facilitator": facilitator_public(fac),
        "smoke_test": smoke,
        "proxy_secret": proxy_secret,  # generated by us; shown ONCE (optional anti-bypass)
        "next_steps": [
            (f"We reached your upstream (HTTP {smoke.get('http_status')})."
             if smoke.get("reachable")
             else f"Heads up: we could NOT reach your upstream ({smoke.get('error') or 'no response'}). Fix it before going live."),
            f"After approval, callers pay + call at {gw_url}/<path>.",
            "Optional: have your upstream require the X-Hub-Secret header above to block direct-bypass calls.",
        ],
    }


@router.post("/api/v1/admin/approve")
async def approve(payload: dict, request: Request,
                  authorization: str | None = Header(default=None)) -> dict:
    settings = request.app.state.settings
    db = request.app.state.db
    _require_admin(authorization, settings)

    slug = payload.get("service_slug")
    service = db.service_with_payout(slug) if slug else None
    if service is None:
        raise HTTPException(404, "service not found")

    # probe upstream reachability (best-effort)
    health = "unknown"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.request("HEAD", service["upstream_base_url"])
            health = "ok" if r.status_code < 500 else "degraded"
    except httpx.HTTPError:
        health = "down"
    db.set_service_health(slug, health)
    db.set_service_status(slug, "live")

    mirrored = await _mirror_to_directory(settings, service)
    log.info("approved %s (health=%s, mirrored=%s)", slug, health, mirrored)
    return {"status": "live", "service_slug": slug, "health": health, "mirrored": mirrored}


@router.post("/api/v1/admin/reject")
async def reject(payload: dict, request: Request,
                 authorization: str | None = Header(default=None)) -> dict:
    settings = request.app.state.settings
    db = request.app.state.db
    _require_admin(authorization, settings)
    slug = payload.get("service_slug")
    if not slug or db.get_service(slug) is None:
        raise HTTPException(404, "service not found")
    db.set_service_status(slug, "rejected")
    return {"status": "rejected", "service_slug": slug}


@router.get("/api/v1/admin/services")
async def admin_list(request: Request, authorization: str | None = Header(default=None)) -> list[dict]:
    settings = request.app.state.settings
    _require_admin(authorization, settings)
    return [_public_view(s) for s in request.app.state.db.list_services()]


@router.get("/api/v1/facilitators")
async def list_facilitators() -> dict:
    """Public list of payment backends a seller can pick, with their terms."""
    items = [facilitator_public(n) for n in SELECTABLE_FACILITATORS]
    return {"default": get_settings().facilitator,
            "facilitators": [i for i in items if i]}


@router.get("/api/v1/services")
async def list_live(request: Request) -> list[dict]:
    return [_public_view(s) for s in request.app.state.db.list_services(status="live")]


@router.get("/api/v1/services/{slug}")
async def get_one(slug: str, request: Request) -> dict:
    svc = request.app.state.db.service_with_payout(slug)
    if svc is None or svc["status"] != "live":
        raise HTTPException(404, "no live service")
    return _public_view(svc)


@router.get("/api/v1/services/{slug}/detail")
async def get_detail(slug: str, request: Request) -> dict:
    db = request.app.state.db
    svc = db.service_with_payout(slug)
    if svc is None or svc["status"] != "live":
        raise HTTPException(404, "no live service")
    return {
        "service": _public_view(svc),
        "stats": db.service_stats(svc["id"]),
        "recent_payments": db.recent_payments(svc["id"]),
    }


# --- needs (demand side): buyers/agents post what they want built ---

@router.post("/api/v1/needs")
async def post_need(req: NeedRequest, request: Request) -> dict:
    need_id = request.app.state.db.create_need(
        title=req.title.strip(), description=(req.description or None),
        category=(req.category or None), budget_usd=req.budget_usd,
        contact=(req.contact or None),
    )
    log.info("need posted: id=%s title=%r", need_id, req.title[:60])
    return {"status": "open", "need_id": need_id}


@router.get("/api/v1/needs")
async def list_needs(request: Request) -> list[dict]:
    # contact is intentionally omitted from the public board to curb scraping/spam.
    return request.app.state.db.list_needs(status="open")


async def _mirror_to_directory(settings, service: dict) -> bool:
    """Best-effort push of an approved listing into agent-tools.cloud (source=hosting)."""
    if not settings.directory_submit_url:
        return False
    payload = {
        "name": service["slug"],
        "url": f"{settings.public_url.rstrip('/')}/gw/{service['slug']}/",
        "description": service.get("description") or "",
        "category": service.get("category") or "hosted",
        "price_usd": service["price_usdc"],
        "source": "hosting",
    }
    headers = {}
    if settings.directory_submit_token:
        headers["Authorization"] = f"Bearer {settings.directory_submit_token}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(settings.directory_submit_url, json=payload, headers=headers)
            return r.status_code < 300
    except httpx.HTTPError:
        return False
