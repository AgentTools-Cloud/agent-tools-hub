"""Runtime config loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_MAINNET_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base mainnet USDC (Circle)
_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # Base Sepolia USDC

# Built-in facilitator registry. A seller picks one per service (or the hub
# default applies). Each entry carries everything the public "backends" page
# needs to render clear terms, plus the chain/asset settlement uses.
#   label/terms : human-facing copy (shown on /backends and the submit form)
#   url         : facilitator base (POST /settle, /verify, GET /supported)
#   network     : default CAIP-2 settlement network (seller may override)
#   usdc        : USDC asset address on that network
#   needs_key   : facilitator requires a Bearer token to settle
#   testnet     : settles in worthless test USDC (dogfood only)
#   free_tier   : short free-tier description
#   gas         : who pays on-chain gas
# Money always settles straight to the seller's payTo — the hub never holds it.
FACILITATOR_PRESETS: dict[str, dict] = {
    "payai": {
        "label": "PayAI",
        "url": "https://facilitator.payai.network",
        "network": "eip155:8453",
        "usdc": _MAINNET_USDC,
        "needs_key": False,
        "testnet": False,
        "free_tier": "10,000 settlements / month free, no API key",
        "gas": "PayAI sponsors gas + RPC",
        "networks": ["eip155:8453", "eip155:137", "eip155:42161",
                     "eip155:43114", "eip155:1329", "eip155:196",
                     "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"],
        "terms": "Free up to 10,000 settlements/month with no account or key; "
                 "beyond that ~$0.001/settlement (covers gas+RPC). 58 (scheme,"
                 "network) pairs — widest chain coverage. Default backend.",
        "homepage": "https://docs.payai.network/x402/facilitators/pricing",
    },
    "x402fi": {
        "label": "x402.fi",
        "url": "https://facilitator.x402.fi",
        "network": "eip155:8453",
        "usdc": _MAINNET_USDC,
        "needs_key": False,
        "testnet": False,
        "free_tier": "Free, no API key",
        "gas": "Facilitator sponsors gas",
        "networks": ["eip155:8453", "eip155:1", "eip155:137", "eip155:43114",
                     "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"],
        "terms": "Open, no-auth facilitator covering Base/Ethereum/Polygon/"
                 "Avalanche + Solana mainnet. Good Solana-mainnet alternative.",
        "homepage": "https://x402.fi",
    },
    "mogami": {
        "label": "Mogami",
        "url": "https://facilitator.mogami.tech",
        "network": "eip155:8453",
        "usdc": _MAINNET_USDC,
        "needs_key": False,
        "testnet": False,
        "free_tier": "Free, no API key",
        "gas": "Facilitator sponsors gas",
        "networks": ["eip155:8453"],
        "terms": "Base-mainnet facilitator, also self-hostable via Docker — the "
                 "path to running your own settlement later.",
        "homepage": "https://mogami.tech",
    },
    "payai-testnet": {
        "label": "PayAI (testnet)",
        "url": "https://facilitator.payai.network",
        "network": "eip155:84532",
        "usdc": _SEPOLIA_USDC,
        "needs_key": False,
        "testnet": True,
        "free_tier": "Free",
        "gas": "Sponsored",
        "networks": ["eip155:84532"],
        "terms": "Base Sepolia testnet — settles worthless test USDC. For "
                 "dogfooding the full flow without real money.",
        "homepage": "https://docs.payai.network",
    },
    "x402-org": {
        "label": "x402.org (testnet)",
        "url": "https://www.x402.org/facilitator",
        "network": "eip155:84532",
        "usdc": _SEPOLIA_USDC,
        "needs_key": False,
        "testnet": True,
        "free_tier": "Free",
        "gas": "Sponsored",
        "networks": ["eip155:84532"],
        "terms": "Coinbase-hosted Base Sepolia testnet. No key, no gas — dogfood only.",
        "homepage": "https://www.x402.org",
    },
    "cdp": {
        "label": "Coinbase CDP",
        "url": "https://api.cdp.coinbase.com/platform/v2/x402",
        "network": "eip155:8453",
        "usdc": _MAINNET_USDC,
        "needs_key": True,
        "testnet": False,
        "free_tier": "1,000 settlements / month free",
        "gas": "CDP sponsors gas",
        "networks": ["eip155:8453", "eip155:137", "eip155:42161"],
        "terms": "Coinbase CDP, Base mainnet. Requires a CDP API key (Ed25519 "
                 "JWT) even on the free tier. Pick if you want Coinbase backing.",
        "homepage": "https://docs.cdp.coinbase.com",
    },
    "self": {
        "label": "Self-hosted",
        "url": "https://facilitator.agent-tools.cloud",
        "network": "eip155:8453",
        "usdc": _MAINNET_USDC,
        "needs_key": False,
        "testnet": False,
        "free_tier": "—",
        "gas": "You pay gas",
        "networks": ["eip155:8453"],
        "terms": "Self-hosted (AgentTools-Cloud/facilitator). You run it, you "
                 "pay gas. Not yet deployed.",
        "homepage": "https://hub.agent-tools.cloud",
    },
}

# Backends a seller may pick for a new service (live mainnet first, then testnet).
SELECTABLE_FACILITATORS = ["payai", "x402fi", "mogami", "payai-testnet"]


def facilitator_public(name: str) -> dict | None:
    """A preset trimmed to public-safe fields for the /backends page + API."""
    p = FACILITATOR_PRESETS.get(name)
    if not p:
        return None
    return {
        "id": name,
        "label": p.get("label", name),
        "network": p["network"],
        "networks": p.get("networks") or [p["network"]],
        "testnet": p.get("testnet", False),
        "needs_key": p.get("needs_key", False),
        "free_tier": p.get("free_tier"),
        "gas": p.get("gas"),
        "terms": p.get("terms"),
        "homepage": p.get("homepage"),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # service
    listen_host: str = "0.0.0.0"
    listen_port: int = 9300
    public_url: str = "https://hub.agent-tools.cloud"

    # upstream facilitator: a preset name (x402-org | cdp | self) OR a full URL.
    # Money always settles straight to the seller payTo — the hub never holds funds.
    facilitator: str = "payai"
    # optional bearer token for facilitators that need one (e.g. custom / CDP)
    facilitator_api_key: str = ""

    # chain / asset — leave empty to inherit from the facilitator preset.
    network: str = ""
    usdc_address_base: str = ""

    # secrets
    fernet_key: str = ""
    admin_token: str = ""

    # ops
    log_level: str = "INFO"
    db_path: str = "/var/lib/agent-tools-hub/hub.db"

    # directory mirror (optional)
    directory_submit_url: str = ""
    directory_submit_token: str = ""

    # --- resolved facilitator config (preset-aware) ---
    @property
    def _preset(self) -> dict | None:
        return FACILITATOR_PRESETS.get(self.facilitator.strip())

    @property
    def facilitator_url(self) -> str:
        fac = self.facilitator.strip()
        if fac.startswith(("http://", "https://")):
            return fac.rstrip("/")
        preset = self._preset
        if not preset:
            raise RuntimeError(
                f"unknown FACILITATOR '{fac}'; use one of {list(FACILITATOR_PRESETS)} or a full URL"
            )
        return preset["url"].rstrip("/")

    @property
    def resolved_network(self) -> str:
        if self.network.strip():
            return self.network.strip()
        preset = self._preset
        return preset["network"] if preset else "eip155:8453"

    @property
    def resolved_usdc(self) -> str:
        if self.usdc_address_base.strip():
            return self.usdc_address_base.strip()
        preset = self._preset
        return preset["usdc"] if preset else _MAINNET_USDC

    @property
    def facilitator_needs_key(self) -> bool:
        preset = self._preset
        return bool(preset and preset["needs_key"])


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
