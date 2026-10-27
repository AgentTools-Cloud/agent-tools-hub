"""Buyer-facing machine-readable catalog built from the live services in the DB.

  /.well-known/x402  -> x402 discovery descriptor (resources + method + probe_body)
  /llms.txt          -> plain-text guide for LLM agents
  /v1/models         -> OpenAI-style list of the fixed models the hub sells

Everything here is derived from the same per-service request policy the
gateway enforces, so what we advertise is exactly what a paid call accepts.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import x402

router = APIRouter()

CHAT_PATH = "v1/chat/completions"


def policy(service: dict) -> dict:
    try:
        value = json.loads(service.get("request_policy_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def call_path(service: dict) -> str:
    paths = policy(service).get("allowed_paths")
    if isinstance(paths, list) and len(paths) == 1:
        return str(paths[0]).lstrip("/")
    return ""


def call_method(service: dict) -> str:
    methods = policy(service).get("allowed_methods")
    if isinstance(methods, list) and methods:
        upper = [str(m).upper() for m in methods]
        return "POST" if "POST" in upper else upper[0]
    return "POST"


def is_chat(service: dict) -> bool:
    return call_path(service) == CHAT_PATH


def limits(service: dict) -> dict:
    p = policy(service)
    out: dict[str, Any] = {}
    if p.get("fixed_model"):
        out["model"] = p["fixed_model"]
    if p.get("allow_stream") is False:
        out["stream"] = False
    if isinstance(p.get("max_output_tokens"), int):
        out["max_output_tokens"] = p["max_output_tokens"]
    if isinstance(p.get("max_request_bytes"), int):
        out["max_request_bytes"] = p["max_request_bytes"]
    return out


def gateway_url(public: str, service: dict) -> str:
    return f"{public.rstrip('/')}/gw/{service['slug']}/{call_path(service)}"


def request_schema(service: dict) -> dict:
    """JSON schema for the request body a paid call accepts."""
    if not is_chat(service):
        return {"type": "object",
                "description": service.get("description") or "Upstream request body."}
    lim = limits(service)
    props: dict[str, Any] = {
        "messages": {
            "type": "array", "minItems": 1,
            "items": {"type": "object", "required": ["role", "content"],
                      "properties": {"role": {"type": "string",
                                              "enum": ["system", "user", "assistant", "tool"]},
                                     "content": {"type": "string"}}},
        },
        "temperature": {"type": "number", "minimum": 0, "maximum": 2},
        "top_p": {"type": "number", "minimum": 0, "maximum": 1},
    }
    if lim.get("model"):
        props["model"] = {"type": "string", "enum": [lim["model"]],
                          "description": "Optional; the service serves only this model."}
    tokens = {"type": "integer", "minimum": 1}
    if lim.get("max_output_tokens"):
        tokens["maximum"] = lim["max_output_tokens"]
        tokens["default"] = lim["max_output_tokens"]
    props["max_tokens"] = tokens
    if lim.get("stream") is False:
        props["stream"] = {"type": "boolean", "enum": [False]}
    return {"type": "object", "required": ["messages"], "properties": props}


def request_example(service: dict) -> dict:
    if not is_chat(service):
        return {}
    lim = limits(service)
    body: dict[str, Any] = {}
    if lim.get("model"):
        body["model"] = lim["model"]
    body["messages"] = [{"role": "user", "content": "Say hello in one sentence."}]
    body["max_tokens"] = 64
    return body


def response_example(service: dict) -> dict:
    if not is_chat(service):
        return {}
    return {
        "id": "chatcmpl-...", "object": "chat.completion", "created": 1761600000,
        "model": limits(service).get("model") or "model",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "Hello!"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    }


def network_for(request: Request, service: dict) -> tuple[str, str]:
    pool = request.app.state.facilitator_pool
    backend = pool.resolved_backend(service.get("facilitator"))
    return pool.settlement(backend, service.get("payout_network"))


def resource_entry(request: Request, service: dict) -> dict:
    public = request.app.state.settings.public_url
    net, usdc = network_for(request, service)
    method = call_method(service)
    entry: dict[str, Any] = {
        "resource": gateway_url(public, service),
        "method": method,
        "description": service.get("description") or f"Paid API {service['slug']}",
        "category": service.get("category"),
        "price_usdc": service["price_usdc"],
        "accepts": [{
            "scheme": "exact", "network": net, "asset": usdc,
            "amount": x402.usdc_atomic(service["price_usdc"]),
            "payTo": service["payout_address"],
        }],
        "mimeType": "application/json",
        "charged": "only when the upstream call succeeds (2xx)",
        "limits": limits(service),
        "input_schema": request_schema(service),
        "input_example": request_example(service),
        "output_example": response_example(service),
        "docs": f"{public.rstrip('/')}/services/{service['slug']}",
    }
    if method == "POST":
        # Unpaid POST {} answers the 402 challenge; health checkers may use it.
        entry["probe_body"] = {}
    return entry


def live_services(request: Request) -> list[dict]:
    return request.app.state.db.list_services(status="live")


@router.get("/.well-known/x402")
@router.get("/.well-known/x402.json", include_in_schema=False)
async def well_known(request: Request) -> JSONResponse:
    public = request.app.state.settings.public_url.rstrip("/")
    doc = {
        "x402Version": x402.X402_VERSION,
        "name": "agent-tools hub",
        "description": "x402 pay-per-call APIs. Pay USDC per request; failed "
                       "upstream calls are not charged.",
        "baseUrl": public,
        "docs": public + "/llms.txt",
        "resources": [resource_entry(request, s) for s in live_services(request)],
    }
    return JSONResponse(doc, headers={"Cache-Control": "public, max-age=300"})


@router.get("/v1/models")
async def models(request: Request) -> dict:
    public = request.app.state.settings.public_url
    data = []
    for s in live_services(request):
        model = limits(s).get("model")
        if not (is_chat(s) and model):
            continue
        lim = limits(s)
        data.append({
            "id": model, "object": "model", "created": int(s.get("created_at") or 0),
            "owned_by": "agent-tools-hub",
            "x402": {"endpoint": gateway_url(public, s), "method": "POST",
                     "price_usdc_per_call": s["price_usdc"],
                     "max_output_tokens": lim.get("max_output_tokens"),
                     "stream": lim.get("stream", True)},
        })
    return {"object": "list", "data": data}


def llms_text(request: Request) -> str:
    public = request.app.state.settings.public_url.rstrip("/")
    lines = [
        "# agent-tools hub",
        "",
        "> x402 pay-per-call APIs. Each call is paid in USDC on Base via the x402 "
        "protocol (v2, scheme `exact`). No account, no API key.",
        "",
        "## How to call",
        "",
        "1. Send the request. Without payment the gateway answers HTTP 402 with a "
        "base64 JSON challenge in the `PAYMENT-REQUIRED` header (price, payTo, network, asset).",
        "2. Sign it with an x402 client (e.g. `@x402/fetch` + `@x402/evm`) and retry "
        "with the `PAYMENT-SIGNATURE` header.",
        "3. The hub verifies the payment, calls the upstream, and settles only if the "
        "upstream answered 2xx. Failed calls are not charged. The settlement tx is "
        "returned in `PAYMENT-RESPONSE` / `X-Payment-Tx`.",
        "",
        f"Machine-readable: {public}/.well-known/x402 · {public}/v1/models · "
        f"{public}/api/v1/services",
        "",
        "## Services",
        "",
    ]
    services = live_services(request)
    if not services:
        lines.append("No live services right now.")
    for s in services:
        net, _ = network_for(request, s)
        lim = limits(s)
        lines.append(f"### {s['slug']}")
        lines.append("")
        if s.get("description"):
            lines.append(s["description"])
            lines.append("")
        lines.append(f"- Endpoint: `{call_method(s)} {gateway_url(public, s)}`")
        lines.append(f"- Price: ${s['price_usdc']} USDC per call ({net})")
        if lim.get("model"):
            lines.append(f"- Model: `{lim['model']}` (only this model)")
        if lim.get("stream") is False:
            lines.append("- Streaming: not supported (`stream` must be false or omitted)")
        if lim.get("max_output_tokens"):
            lines.append(f"- max_tokens: up to {lim['max_output_tokens']} "
                         f"(default {lim['max_output_tokens']})")
        example = request_example(s)
        if example:
            lines.append(f"- Example body: `{json.dumps(example, separators=(',', ':'))}`")
        lines.append(f"- Docs: {public}/services/{s['slug']}")
        lines.append("")
    return "\n".join(lines) + "\n"


@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms(request: Request) -> PlainTextResponse:
    return PlainTextResponse(llms_text(request),
                             headers={"Cache-Control": "public, max-age=300"})
