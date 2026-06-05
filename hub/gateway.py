"""Multi-tenant reverse-proxy gateway with per-call x402.

Flow for ANY /gw/{slug}/{path}:
  1. no X-PAYMENT  -> 402 + challenge (payTo = seller, price, USDC/Base, bazaar)
  2. with X-PAYMENT -> facilitator /settle (USDC buyer -> seller payTo, hub takes nothing)
  3. settled       -> proxy to upstream, inject seller's upstream key + X-Hub-Secret
                      (anti-freeload: seller's origin verifies the secret)

The hub never holds funds; settlement is pass-through to the seller's payTo.
"""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import x402

log = logging.getLogger(__name__)
router = APIRouter()

# Headers we never forward upstream.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}
# Buyer-supplied headers we strip before reaching the seller's origin.
_STRIP_INBOUND = {"x-payment", "authorization", "x-hub-secret"}


def _challenge_response(*, service: dict, requirements: dict, method: str,
                        resource_url: str, error: str) -> JSONResponse:
    body = x402.build_challenge(requirements=requirements, service=service,
                                method=method, resource_url=resource_url, error=error)
    # x402 v2 clients read the challenge from the PAYMENT-REQUIRED header (base64),
    # not the body. Body stays human-readable for browsers.
    return JSONResponse(
        status_code=402, content=body,
        headers={"PAYMENT-REQUIRED": x402.encode_challenge_header(body)},
    )


@router.api_route(
    "/gw/{slug}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def gateway(slug: str, path: str, request: Request) -> Response:
    app = request.app
    settings = app.state.settings
    db = app.state.db
    box = app.state.secret_box
    facilitator = app.state.facilitator
    proxy: httpx.AsyncClient = app.state.proxy_client

    service = db.service_with_payout(slug)
    if service is None or service["status"] != "live":
        return JSONResponse(status_code=404, content={"error": f"no live service '{slug}'"})

    resource_url = f"{settings.public_url.rstrip('/')}/gw/{slug}/{path}"
    requirements = x402.build_requirements(
        service=service, resource_url=resource_url,
        network=settings.resolved_network, usdc_address=settings.resolved_usdc,
    )

    # --- payment gate ---
    payer: str | None = None
    tx_hash: str | None = None
    pay_header = request.headers.get("x-payment")
    if not pay_header:
        return _challenge_response(service=service, requirements=requirements,
                                   method=request.method, resource_url=resource_url,
                                   error="X-PAYMENT header is required")

    payload = x402.decode_payment_header(pay_header)
    if payload is None:
        return _challenge_response(service=service, requirements=requirements,
                                   method=request.method, resource_url=resource_url,
                                   error="malformed X-PAYMENT header")

    settle = await facilitator.settle(payment_payload=payload, payment_requirements=requirements)
    if not settle.get("success"):
        return _challenge_response(
            service=service, requirements=requirements, method=request.method,
            resource_url=resource_url,
            error=f"payment not settled: {settle.get('errorReason') or 'unknown'}",
        )
    payer = settle.get("payer")
    tx_hash = settle.get("transaction")

    # --- proxy to upstream ---
    started = time.monotonic()
    upstream_url = f"{service['upstream_base_url'].rstrip('/')}/{path}"
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() not in _STRIP_INBOUND
    }
    # inject seller's own upstream key (decrypted) + proxy secret (anti-freeload)
    auth_header = service.get("upstream_auth_header")
    if auth_header:
        secret_val = box.decrypt(service.get("upstream_auth_enc"))
        if secret_val:
            fwd_headers[auth_header] = secret_val
    fwd_headers["X-Hub-Secret"] = service["proxy_secret"]

    body = await request.body()
    try:
        upstream_resp = await proxy.request(
            request.method, upstream_url,
            params=dict(request.query_params), headers=fwd_headers, content=body,
        )
    except httpx.HTTPError as e:
        log.error("upstream proxy error for %s: %s", upstream_url, e)
        db.log_usage(service_id=service["id"], path=path, method=request.method,
                     http_status=502, paid=True, payer=payer,
                     amount_atomic=requirements["maxAmountRequired"], tx_hash=tx_hash,
                     latency_ms=int((time.monotonic() - started) * 1000))
        return JSONResponse(status_code=502, content={"error": "upstream unreachable"})

    latency_ms = int((time.monotonic() - started) * 1000)
    db.log_usage(service_id=service["id"], path=path, method=request.method,
                 http_status=upstream_resp.status_code, paid=True, payer=payer,
                 amount_atomic=requirements["maxAmountRequired"], tx_hash=tx_hash,
                 latency_ms=latency_ms)

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    if tx_hash:
        resp_headers["X-Payment-Tx"] = tx_hash
    return Response(content=upstream_resp.content, status_code=upstream_resp.status_code,
                    headers=resp_headers, media_type=upstream_resp.headers.get("content-type"))
