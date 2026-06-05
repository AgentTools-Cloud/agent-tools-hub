"""x402 challenge construction + X-PAYMENT parsing.

Emits x402 **v2** challenges (the version our default facilitator, x402.org,
advertises in /supported, with CAIP-2 networks like eip155:84532). v2 uses
`amount` + top-level `resource`; the official x402 client registers `eip155:*`
for v2, so CAIP-2 networks match and sign. Payment headers are CORS-exposed
(main.py middleware + nginx), the conversion_fix lesson.
"""

from __future__ import annotations

import base64
import json

# x402 protocol version emitted in the 402 challenge body.
X402_VERSION = 2


def usdc_atomic(price_usdc: float) -> str:
    """USD price -> 6-decimal USDC atomic units, as a string."""
    return str(int(round(price_usdc * 1_000_000)))


def build_requirements(*, service: dict, resource_url: str, network: str,
                       usdc_address: str) -> dict:
    """One v2 PaymentRequirements entry. MUST be byte-identical between the
    challenge and the /settle call (facilitator re-derives EIP-712 from it)."""
    return {
        "scheme": "exact",
        "network": network,
        "asset": usdc_address,
        "amount": usdc_atomic(service["price_usdc"]),
        "payTo": service["payout_address"],
        "maxTimeoutSeconds": 120,
        "extra": {"name": "USDC", "version": "2"},
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
                    resource_url: str = "",
                    error: str = "X-PAYMENT header is required") -> dict:
    return {
        "x402Version": X402_VERSION,
        "error": error,
        "resource": {
            "url": resource_url,
            "description": service.get("description") or f"Access to {service['slug']}",
        },
        "accepts": [requirements],
        "extensions": _bazaar(service, method),
    }


def encode_challenge_header(challenge: dict) -> str:
    """x402 v2 carries the challenge in the PAYMENT-REQUIRED response header,
    base64(JSON). Body is kept human-readable but clients read the header."""
    return base64.b64encode(json.dumps(challenge).encode("utf-8")).decode("utf-8")




def decode_payment_header(header_value: str) -> dict | None:
    """Decode the base64 X-PAYMENT header into the payment payload dict."""
    try:
        raw = base64.b64decode(header_value)
        return json.loads(raw)
    except Exception:
        return None
