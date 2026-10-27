"""Multi-tenant reverse-proxy gateway with per-call x402.

Flow for ANY /gw/{slug}/{path}:
  1. no payment signature -> 402 + challenge (payTo = seller, price, USDC/Base, bazaar)
  2. with PAYMENT-SIGNATURE (or legacy X-PAYMENT) -> facilitator /settle
  3. settled       -> proxy to upstream, inject seller's upstream key + X-Hub-Secret
                      (anti-freeload: seller's origin verifies the secret)

The hub never holds funds; settlement is pass-through to the seller's payTo.
"""

from __future__ import annotations

import json as _json
import logging
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import safety, x402

# Caps on what flows through the hop. A seller's own limits are their business;
# what passes through us stays bounded so one upstream can't exhaust the hub.
_MAX_REQUEST_BODY = 20 * 1024 * 1024    # 20 MiB inbound body
_MAX_RESPONSE_BODY = 25 * 1024 * 1024   # 25 MiB upstream response

log = logging.getLogger(__name__)
router = APIRouter()

# Headers we never forward upstream.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}
# Buyer-supplied headers we strip before reaching the seller's origin.
_STRIP_INBOUND = {
    "payment-signature", "x-payment", "authorization", "x-hub-secret",
    # The hub rewrites JSON responses, so upstream encoding must be negotiated
    # by httpx itself; forwarding Cloudflare's br can yield undecodable bytes.
    "accept-encoding",
}
_SAFE_PUBLIC_RESPONSE_HEADERS = {"content-type", "cache-control", "retry-after"}


# MCP (JSON-RPC) methods that are protocol handshake / metadata, not billable
# work. A hosted MCP server must answer these *before* a client can ever call a
# tool, so charging for them 402-blocks the connection. We free-pass them
# (still proxied upstream) and only gate the actual tools/call behind payment.
_MCP_FREE_METHODS = {
    "initialize", "notifications/initialized", "notifications/cancelled",
    "ping", "tools/list", "resources/list", "prompts/list",
    "resources/templates/list", "logging/setlevel", "completion/complete",
}


def _is_free_mcp_request(raw_body: bytes) -> bool:
    """True if the request body is a JSON-RPC MCP message whose method is a
    non-billable handshake/metadata call (or a notification). Plain REST APIs
    never send these, so this is a no-op for non-MCP upstreams.
    """
    if not raw_body:
        return False
    try:
        msg = _json.loads(raw_body)
    except Exception:
        return False
    # batch: free only if EVERY sub-message is a free method
    if isinstance(msg, list):
        return bool(msg) and all(_is_free_mcp_request(_json.dumps(m).encode())
                                 for m in msg)
    if not isinstance(msg, dict):
        return False
    method = msg.get("method")
    if not isinstance(method, str):
        return False
    # any notification (no id, method starts with "notifications/") is free
    if method.startswith("notifications/"):
        return True
    return method in _MCP_FREE_METHODS


def _payment_header(headers) -> str | None:
    return headers.get("payment-signature") or headers.get("x-payment")


def _policy_response(status_code: int, error: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error})


def _policy_field(service: dict, key: str) -> set[str]:
    try:
        policy = _json.loads(service.get("request_policy_json") or "{}")
    except (TypeError, ValueError):
        return set()
    values = policy.get(key) if isinstance(policy, dict) else None
    return set(values) if isinstance(values, list) else set()


def _policy_allowed_methods(service: dict) -> set[str]:
    return {str(x).upper() for x in _policy_field(service, "allowed_methods")}


def _policy_allowed_paths(service: dict) -> set[str]:
    return {str(x).lstrip("/") for x in _policy_field(service, "allowed_paths")}


def _apply_request_policy(*, service: dict, path: str, method: str,
                          body: bytes) -> tuple[bytes, JSONResponse | None]:
    # Apply optional per-service constraints before charging the buyer.
    raw_policy = service.get("request_policy_json")
    if not raw_policy:
        return body, None
    try:
        policy = _json.loads(raw_policy)
    except (TypeError, ValueError):
        log.error("invalid request policy for service %s", service.get("slug"))
        return body, _policy_response(503, "service request policy is invalid")
    if not isinstance(policy, dict):
        return body, _policy_response(503, "service request policy is invalid")

    allowed_methods = policy.get("allowed_methods")
    if allowed_methods and method.upper() not in {str(x).upper() for x in allowed_methods}:
        return body, _policy_response(405, "method not allowed for this service")
    allowed_paths = policy.get("allowed_paths")
    if allowed_paths and path not in {str(x).lstrip("/") for x in allowed_paths}:
        return body, _policy_response(404, "resource not offered by this service")
    max_bytes = policy.get("max_request_bytes")
    if isinstance(max_bytes, int) and max_bytes > 0 and len(body) > max_bytes:
        return body, _policy_response(413, "request body exceeds service limit")

    needs_json = bool(policy.get("require_json") or policy.get("fixed_model")
                      or policy.get("upstream_model")
                      or policy.get("max_output_tokens") is not None
                      or policy.get("allow_stream") is False)
    if not needs_json:
        return body, None
    try:
        payload = _json.loads(body)
    except (TypeError, ValueError):
        return body, _policy_response(400, "valid JSON body required")
    if not isinstance(payload, dict):
        return body, _policy_response(400, "JSON body must be an object")

    fixed_model = policy.get("fixed_model")
    upstream_model = policy.get("upstream_model")
    if upstream_model is not None and (
            not isinstance(upstream_model, str) or not upstream_model
    ):
        return body, _policy_response(503, "service request policy is invalid")
    requested_model = payload.get("model")
    if fixed_model:
        if requested_model not in (None, "", fixed_model):
            return body, _policy_response(422, "this service only offers its fixed model")
        payload["model"] = upstream_model or fixed_model
    if policy.get("allow_stream") is False and payload.get("stream") is True:
        return body, _policy_response(422, "streaming is not offered by this service")

    max_output = policy.get("max_output_tokens")
    if isinstance(max_output, int) and max_output > 0:
        found = False
        for field in ("max_tokens", "max_completion_tokens"):
            value = payload.get(field)
            if value is None:
                continue
            found = True
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                return body, _policy_response(422, f"{field} must be a positive integer")
            if value > max_output:
                return body, _policy_response(422, f"{field} exceeds service limit {max_output}")
        if not found:
            payload["max_tokens"] = max_output

    return _json.dumps(payload, separators=(",", ":")).encode("utf-8"), None


def _sanitize_upstream_response(*, service: dict, content: bytes,
                                status_code: int) -> tuple[bytes, int, bool]:
    try:
        policy = _json.loads(service.get("request_policy_json") or "{}")
    except (TypeError, ValueError):
        policy = {}
    if not isinstance(policy, dict) or not policy.get("sanitize_response"):
        return content, status_code, False
    if status_code >= 400:
        body = {"error": "upstream request failed", "status": status_code}
        return _json.dumps(body, separators=(",", ":")).encode(), status_code, True
    try:
        payload = _json.loads(content)
    except (TypeError, ValueError):
        body = {"error": "invalid upstream response"}
        return _json.dumps(body, separators=(",", ":")).encode(), 502, True
    if not isinstance(payload, dict):
        body = {"error": "invalid upstream response"}
        return _json.dumps(body, separators=(",", ":")).encode(), 502, True
    allowed = {"id", "object", "created", "model", "choices", "usage"}
    public = {key: value for key, value in payload.items() if key in allowed}
    fixed_model = policy.get("fixed_model")
    if isinstance(fixed_model, str) and fixed_model:
        public["model"] = fixed_model
    usage = public.get("usage")
    if isinstance(usage, dict):
        usage_fields = {
            "prompt_tokens", "completion_tokens", "total_tokens",
            "prompt_tokens_details", "completion_tokens_details",
        }
        public["usage"] = {
            key: value for key, value in usage.items() if key in usage_fields
        }
    return _json.dumps(public, separators=(",", ":")).encode(), status_code, True


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
    proxy: httpx.AsyncClient = app.state.proxy_client

    service = db.service_with_payout(slug)
    if service is None or service["status"] != "live":
        return JSONResponse(status_code=404, content={"error": f"no live service '{slug}'"})

    resource_url = f"{settings.public_url.rstrip('/')}/gw/{slug}/{path}"

    tx_hash: str | None = None
    # Read the body once; we need it both to detect free MCP handshakes and to
    # forward it upstream.
    body = await request.body()
    if len(body) > _MAX_REQUEST_BODY:
        return JSONResponse(status_code=413,
                            content={"error": "request body too large"})

    challenge_method = request.method
    allowed = _policy_allowed_methods(service)
    if (request.method in ("GET", "HEAD") and allowed
            and request.method not in allowed
            and not _payment_header(request.headers)):
        # Health checkers and indexers probe with GET/HEAD; answer with the
        # payment challenge advertising the method the service accepts.
        challenge_method = "POST" if "POST" in allowed else sorted(allowed)[0]
        allowed_paths = _policy_allowed_paths(service)
        if allowed_paths and path not in allowed_paths:
            return _policy_response(404, "resource not offered by this service")
        body = b""
    else:
        body, policy_error = _apply_request_policy(
            service=service, path=path, method=request.method, body=body)
        if policy_error is not None:
            return policy_error

    # --- MCP-aware free pass: handshake / list methods are not billable. A
    # hosted MCP server must answer initialize + tools/list before any client
    # can call a tool, so charging for them would 402-block the connection.
    if _is_free_mcp_request(body):
        return await _proxy_upstream(
            proxy=proxy, box=box, db=db, service=service, path=path,
            request=request, body=body, payer=None, tx_hash=tx_hash,
            amount_atomic="0", paid=False)

    pool = app.state.facilitator_pool
    backend = pool.resolved_backend(service["facilitator"] if "facilitator" in service.keys() else None)
    net, usdc = pool.settlement(backend, service["payout_network"])
    facilitator = pool.client(backend)
    requirements = x402.build_requirements(
        service=service, resource_url=resource_url,
        network=net, usdc_address=usdc,
    )

    # --- payment gate (tools/call and any non-handshake request) ---
    payer: str | None = None
    pay_header = _payment_header(request.headers)
    if not pay_header:
        return _challenge_response(service=service, requirements=requirements,
                                   method=challenge_method, resource_url=resource_url,
                                   error="PAYMENT-SIGNATURE header is required")

    payload = x402.decode_payment_header(pay_header)
    if payload is None:
        return _challenge_response(service=service, requirements=requirements,
                                   method=request.method, resource_url=resource_url,
                                   error="malformed payment signature header")

    # Verify first, serve, and settle only when the upstream succeeded, so a
    # failed call never charges the buyer. The signed authorization is single-
    # use on-chain; the claim stops concurrent requests reusing it meanwhile.
    verify = await facilitator.verify(payment_payload=payload, payment_requirements=requirements)
    if not verify.get("isValid"):
        return _challenge_response(
            service=service, requirements=requirements, method=request.method,
            resource_url=resource_url,
            error=f"payment not valid: {verify.get('invalidReason') or 'unknown'}",
        )
    claim_key = _authorization_key(payload, verify.get("payer"))
    if not claim_key or not db.claim_payment(claim_key, service["id"]):
        return _challenge_response(
            service=service, requirements=requirements, method=request.method,
            resource_url=resource_url,
            error="payment authorization already in use",
        )

    async def settle_payment():
        result = await facilitator.settle(payment_payload=payload,
                                          payment_requirements=requirements)
        db.finish_payment_claim(claim_key, bool(result.get("success")))
        return result

    try:
        return await _proxy_upstream(
            proxy=proxy, box=box, db=db, service=service, path=path,
            request=request, body=body, payer=verify.get("payer"), tx_hash=None,
            amount_atomic=requirements["amount"], paid=True,
            settle=settle_payment,
            upstream_timeout=_paid_upstream_timeout(requirements))
    finally:
        # No-op once settled; frees the authorization when we never charged.
        db.finish_payment_claim(claim_key, False)


def _authorization_key(payload: dict, payer: str | None) -> str | None:
    auth = ((payload or {}).get("payload") or {}).get("authorization") or {}
    nonce = auth.get("nonce")
    owner = auth.get("from") or payer
    if not nonce or not owner:
        return None
    return f"{str(owner).lower()}:{str(nonce).lower()}"


def _paid_upstream_timeout(requirements: dict) -> float:
    # Leave room inside the authorization's validity window to settle afterwards.
    window = int(requirements.get("maxTimeoutSeconds") or 120)
    return float(max(10, min(window - 30, 300)))


async def _proxy_upstream(*, proxy, box, db, service, path, request, body,
                          payer, tx_hash, amount_atomic, paid,
                          settle=None, upstream_timeout: float | None = None):
    """Forward the (already-read) request to the seller's upstream and relay the
    response. With `settle`, payment is captured only after a 2xx upstream
    response; on any failure the buyer is not charged."""
    started = time.monotonic()
    upstream_url = f"{service['upstream_base_url'].rstrip('/')}/{path}"
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() not in _STRIP_INBOUND
    }
    auth_header = service.get("upstream_auth_header")
    if auth_header:
        secret_val = box.decrypt(service.get("upstream_auth_enc"))
        if secret_val:
            fwd_headers[auth_header] = secret_val
    fwd_headers["X-Hub-Secret"] = service["proxy_secret"]

    # Re-check SSRF at call time: DNS for the upstream host may have changed
    # since registration (rebinding). Refuse if it now points internal.
    _reason = safety.upstream_host_reason(upstream_url)
    if _reason:
        log.warning("blocked upstream %s: %s", upstream_url, _reason)
        db.log_usage(service_id=service["id"], path=path, method=request.method,
                     http_status=502, paid=False, payer=payer,
                     amount_atomic="0", tx_hash=None,
                     latency_ms=int((time.monotonic() - started) * 1000))
        return JSONResponse(status_code=502, content={"error": "upstream blocked"})

    request_kwargs = {}
    if upstream_timeout is not None:
        request_kwargs["timeout"] = httpx.Timeout(
            connect=8.0, read=upstream_timeout, write=60.0, pool=8.0)
    try:
        upstream_resp = await proxy.request(
            request.method, upstream_url,
            params=dict(request.query_params), headers=fwd_headers, content=body,
            **request_kwargs,
        )
    except httpx.HTTPError as e:
        log.error("upstream proxy error for %s: %s", upstream_url, e)
        db.log_usage(service_id=service["id"], path=path, method=request.method,
                     http_status=502, paid=False if settle else paid, payer=payer,
                     amount_atomic="0" if settle else amount_atomic, tx_hash=tx_hash,
                     latency_ms=int((time.monotonic() - started) * 1000))
        return JSONResponse(status_code=502, content={"error": "upstream unreachable"})

    # Cap the relayed response so one upstream can't blow up hub memory.
    content = upstream_resp.content
    if len(content) > _MAX_RESPONSE_BODY:
        log.warning("upstream %s response too large: %d bytes", upstream_url, len(content))
        db.log_usage(service_id=service["id"], path=path, method=request.method,
                     http_status=502, paid=False if settle else paid, payer=payer,
                     amount_atomic="0" if settle else amount_atomic, tx_hash=tx_hash,
                     latency_ms=int((time.monotonic() - started) * 1000))
        return JSONResponse(status_code=502, content={"error": "upstream response too large"})

    content, response_status, sanitized = _sanitize_upstream_response(
        service=service, content=content, status_code=upstream_resp.status_code)
    if settle is not None:
        if 200 <= response_status < 300:
            result = await settle()
            if not result.get("success"):
                log.warning("settle after upstream success failed for %s: %s",
                            service["slug"], result.get("errorReason"))
                db.log_usage(service_id=service["id"], path=path, method=request.method,
                             http_status=402, paid=False, payer=payer, amount_atomic="0",
                             tx_hash=None,
                             latency_ms=int((time.monotonic() - started) * 1000))
                return JSONResponse(status_code=402, content={
                    "error": f"payment not settled: {result.get('errorReason') or 'unknown'}"})
            payer = result.get("payer") or payer
            tx_hash = result.get("transaction")
        else:
            paid, amount_atomic = False, "0"
    latency_ms = int((time.monotonic() - started) * 1000)
    db.log_usage(service_id=service["id"], path=path, method=request.method,
                 http_status=response_status, paid=paid, payer=payer,
                 amount_atomic=amount_atomic, tx_hash=tx_hash,
                 latency_ms=latency_ms)

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
        and (not sanitized or k.lower() in _SAFE_PUBLIC_RESPONSE_HEADERS)
    }

    if tx_hash:
        resp_headers["X-Payment-Tx"] = tx_hash
        resp_headers["PAYMENT-RESPONSE"] = x402.encode_payment_response({
            "success": True, "payer": payer, "transaction": tx_hash,
        })
    media_type = "application/json" if sanitized else upstream_resp.headers.get("content-type")
    return Response(content=content, status_code=response_status,
                    headers=resp_headers, media_type=media_type)
