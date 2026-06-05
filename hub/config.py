"""Runtime config loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Built-in facilitator presets. Pick one by name in FACILITATOR, or pass a full
# URL. Each preset carries the matching network + USDC address (testnet vs
# mainnet USDC differ — using the wrong one breaks settlement).
FACILITATOR_PRESETS: dict[str, dict] = {
    "x402-org": {
        "url": "https://x402.org/facilitator",
        "network": "eip155:84532",  # Base Sepolia testnet
        "usdc": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia USDC
        "needs_key": False,
        "note": "Coinbase hosted, Base Sepolia testnet. No key, no gas — best for dogfood.",
    },
    "cdp": {
        "url": "https://api.cdp.coinbase.com/platform/v2/x402",
        "network": "eip155:8453",  # Base mainnet
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base mainnet USDC
        "needs_key": True,
        "note": "Coinbase CDP, Base mainnet. Requires a CDP API key (JWT).",
    },
    "self": {
        "url": "https://facilitator.agent-tools.cloud",
        "network": "eip155:8453",  # Base mainnet
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base mainnet USDC
        "needs_key": False,
        "note": "Self-hosted (AgentTools-Cloud/facilitator). You run it, you pay gas.",
    },
}

_MAINNET_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # service
    listen_host: str = "0.0.0.0"
    listen_port: int = 9300
    public_url: str = "https://hub.agent-tools.cloud"

    # upstream facilitator: a preset name (x402-org | cdp | self) OR a full URL.
    # Money always settles straight to the seller payTo — the hub never holds funds.
    facilitator: str = "x402-org"
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
