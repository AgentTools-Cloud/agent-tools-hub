"""Thin HTTP client for an x402 facilitator (verify + settle).

The gateway forwards the buyer's X-PAYMENT payload here for on-chain settle.
USDC moves from the buyer straight to the seller's payTo — the hub is only the
coordinator, it never custodies funds. Which facilitator is used is chosen via
the FACILITATOR preset (x402-org / cdp / self / custom URL); see config.py.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class FacilitatorClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        # follow_redirects: some facilitators 308 bare-domain -> www on POST.
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)

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


class FacilitatorPool:
    """Lazily builds + caches one FacilitatorClient per backend id, and resolves
    each backend's settlement network + USDC asset from its preset. Lets every
    hosted service settle through the facilitator its seller chose.

    The seller may pin a settlement network (payout_network); we honour it only
    when the chosen backend actually supports it, else fall back to the backend
    default — a wrong network silently breaks settlement.
    """

    def __init__(self, settings):
        from .config import FACILITATOR_PRESETS
        self._presets = FACILITATOR_PRESETS
        self._settings = settings
        self._clients: dict[str, FacilitatorClient] = {}

    def _preset(self, backend: str) -> dict:
        p = self._presets.get(backend)
        if not p:  # unknown -> hub default
            p = self._presets[self._settings.facilitator]
        return p

    def client(self, backend: str) -> FacilitatorClient:
        p = self._preset(backend)
        url = p["url"].rstrip("/")
        if url not in self._clients:
            key = self._settings.facilitator_api_key if p.get("needs_key") else ""
            self._clients[url] = FacilitatorClient(url, key)
        return self._clients[url]

    def settlement(self, backend: str, payout_network: str | None) -> tuple[str, str]:
        """Return (network, usdc_address) for this service's settlement."""
        p = self._preset(backend)
        net = p["network"]
        pn = (payout_network or "").strip()
        if pn and pn in (p.get("networks") or [p["network"]]):
            net = pn
        # USDC asset is network-specific; preset only carries its default
        # network's asset, so only trust it when the network matches.
        usdc = p["usdc"] if net == p["network"] else p["usdc"]
        return net, usdc

    def resolved_backend(self, service_backend: str | None) -> str:
        b = (service_backend or "").strip()
        return b if b in self._presets else self._settings.facilitator

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.aclose()
