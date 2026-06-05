"""Runtime config loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # service
    listen_host: str = "0.0.0.0"
    listen_port: int = 9300
    public_url: str = "https://hub.agent-tools.cloud"

    # upstream facilitator (verify + settle; money goes straight to seller payTo)
    facilitator_url: str = "https://facilitator.agent-tools.cloud"

    # chain / asset
    network: str = "eip155:8453"
    usdc_address_base: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

    # secrets
    fernet_key: str = ""
    admin_token: str = ""

    # ops
    log_level: str = "INFO"
    db_path: str = "/var/lib/agent-tools-hub/hub.db"

    # directory mirror (optional)
    directory_submit_url: str = ""
    directory_submit_token: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
