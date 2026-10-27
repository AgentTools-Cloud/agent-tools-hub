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
    # Circle USDC uses "USD Coin" on Base mainnet but "USDC" on Base Sepolia.
    token_name = "USD Coin" if network == "eip155:8453" else "USDC"
    return {
        "scheme": "exact",
        "network": network,
        "asset": usdc_address,
        "amount": usdc_atomic(service["price_usdc"]),
        "payTo": service["payout_address"],
        "maxTimeoutSeconds": 120,
        "extra": {"name": token_name, "version": "2"},
    }


def _bazaar(service: dict, method: str) -> dict:
    """Bazaar discovery hint: call shape, input schema and examples, derived
    from the same request policy the gateway enforces."""
    from . import catalog  # local import: catalog imports this module

    path = catalog.call_path(service)
    info: dict = {
        "method": method,
        "path": f"/gw/{service['slug']}/{path}" if path else f"/gw/{service['slug']}/...",
        "note": ("Charged only when the upstream call succeeds (2xx)." if path else
                 "Proxied upstream; append the upstream path after the slug."),
    }
    lim = catalog.limits(service)
    if lim:
        info["limits"] = lim
    example = catalog.request_example(service)
    if example:
        info["input"] = {"type": "http", "method": method,
                         "bodyType": "json", "body": example}
        info["output"] = {"type": "json", "example": catalog.response_example(service)}
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
    schema.update(catalog.request_schema(service))
    schema.setdefault("description", service.get("description") or "Wrapped upstream API.")
    return {"bazaar": {"info": info, "schema": schema}}


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




def encode_payment_response(response: dict) -> str:
    # x402 v2 PAYMENT-RESPONSE is base64(JSON).
    return base64.b64encode(json.dumps(response).encode("utf-8")).decode("utf-8")


def decode_payment_header(header_value: str) -> dict | None:
    # Decode PAYMENT-SIGNATURE or legacy X-PAYMENT base64 JSON.
    try:
        raw = base64.b64decode(header_value)
        return json.loads(raw)
    except Exception:
        return None
