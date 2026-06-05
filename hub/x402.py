"""x402 challenge construction + X-PAYMENT parsing.

Bakes in the two lessons from agent-tools.cloud's $0 post-mortem
(02_conversion_fix.md): every 402 carries an `extensions.bazaar` block so agent
SDKs can auto-generate the call, and the payment headers must be CORS-exposed
(done in main.py middleware + nginx).
"""

from __future__ import annotations

import base64
import json

# x402 protocol version emitted in the 402 challenge body.
X402_VERSION = 1


def usdc_atomic(price_usdc: float) -> str:
    """USD price -> 6-decimal USDC atomic units, as a string."""
    return str(int(round(price_usdc * 1_000_000)))


def build_requirements(*, service: dict, resource_url: str, network: str,
                       usdc_address: str) -> dict:
    """One PaymentRequirements entry (the facilitator re-derives EIP-712 from this,
    so it MUST be byte-identical between challenge and settle)."""
    return {
        "scheme": "exact",
        "network": network,
        "maxAmountRequired": usdc_atomic(service["price_usdc"]),
        "resource": resource_url,
        "description": service.get("description") or f"Access to {service['slug']}",
        "mimeType": "application/json",
        "payTo": service["payout_address"],
        "maxTimeoutSeconds": 120,
        "asset": usdc_address,
        "extra": {"name": "USD Coin", "version": "2"},
    }


def _bazaar(service: dict, method: str) -> dict:
    """Minimal bazaar hint so agent SDKs don't have to guess the call shape."""
    return {
        "bazaar": {
            "info": {
                "method": method,
                "path": f"/gw/{service['slug']}/...",
                "note": "Proxied upstream; append the upstream path after the slug.",
            },
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "description": service.get("description") or "Wrapped upstream API.",
            },
        }
    }


def build_challenge(*, requirements: dict, service: dict, method: str,
                    error: str = "X-PAYMENT header is required") -> dict:
    req = dict(requirements)
    req["extensions"] = _bazaar(service, method)
    return {"x402Version": X402_VERSION, "error": error, "accepts": [req]}


def decode_payment_header(header_value: str) -> dict | None:
    """Decode the base64 X-PAYMENT header into the payment payload dict."""
    try:
        raw = base64.b64decode(header_value)
        return json.loads(raw)
    except Exception:
        return None
