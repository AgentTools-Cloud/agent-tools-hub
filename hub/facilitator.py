"""Thin HTTP client for our own x402 facilitator (JoursBleu/facilitator).

The gateway forwards the buyer's X-PAYMENT payload here for on-chain settle.
USDC moves from the buyer straight to the seller's payTo — the hub is only the
coordinator, it never custodies funds.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class FacilitatorClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def settle(self, *, payment_payload: dict, payment_requirements: dict) -> dict:
        """POST /settle. Returns the facilitator's SettleResponse dict.

        On transport error returns a synthetic failure dict so the caller can
        emit a clean 402 instead of a 500.
        """
        body = {
            "x402Version": payment_payload.get("x402Version", 2),
            "paymentPayload": payment_payload,
            "paymentRequirements": payment_requirements,
        }
        try:
            r = await self._client.post(f"{self._base}/settle", json=body)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            log.warning("facilitator /settle %s: %s", e.response.status_code, e.response.text[:200])
            try:
                return e.response.json()
            except Exception:
                return {"success": False, "errorReason": f"facilitator_http_{e.response.status_code}"}
        except httpx.HTTPError as e:
            log.error("facilitator /settle transport error: %s", e)
            return {"success": False, "errorReason": "facilitator_unreachable"}

    async def supported(self) -> dict | None:
        try:
            r = await self._client.get(f"{self._base}/supported")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return None

    async def aclose(self) -> None:
        await self._client.aclose()
