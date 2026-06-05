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

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter()

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
    upstream_base_url: str
    upstream_auth_header: str | None = None
    upstream_auth_value: str | None = None  # plaintext; encrypted before storage
    price_usdc: float = Field(gt=0)
    description: str | None = None
    category: str | None = None


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
    if not req.upstream_base_url.startswith(("http://", "https://")):
        raise HTTPException(422, "upstream_base_url must be http(s)")
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
    )
    log.info("submit: service=%s id=%s status=pending", req.service_slug, service_id)
    return {
        "status": "pending",
        "service_slug": req.service_slug,
        "proxy_secret": proxy_secret,  # shown ONCE so seller can verify X-Hub-Secret upstream
        "next_steps": [
            "Lock your upstream to only accept requests carrying X-Hub-Secret = proxy_secret.",
            "After approval, point clients at /gw/{service_slug}/...",
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


@router.get("/api/v1/services")
async def list_live(request: Request) -> list[dict]:
    return [_public_view(s) for s in request.app.state.db.list_services(status="live")]


@router.get("/api/v1/services/{slug}")
async def get_one(slug: str, request: Request) -> dict:
    svc = request.app.state.db.service_with_payout(slug)
    if svc is None or svc["status"] != "live":
        raise HTTPException(404, "no live service")
    return _public_view(svc)


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
