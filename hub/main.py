"""FastAPI app entry point for agent-tools hub."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
from .crypto import SecretBox
from .db import DB
from .facilitator import FacilitatorClient
from .gateway import router as gateway_router
from .landing import router as landing_router
from .sellers import router as sellers_router

# x402 payment headers that browser/fetch clients must be able to read.
# (The $0 post-mortem: without exposing these, web agents silently drop the challenge.)
_EXPOSE_HEADERS = "PAYMENT-REQUIRED, PAYMENT-RESPONSE, X-PAYMENT, X-Payment-Tx"


class PaymentCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Expose-Headers"] = _EXPOSE_HEADERS
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        return response


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _setup_logging(settings.log_level)
    log = logging.getLogger(__name__)

    app.state.settings = settings
    app.state.db = DB(settings.db_path)
    app.state.secret_box = SecretBox(settings.fernet_key)
    app.state.facilitator = FacilitatorClient(settings.facilitator_url)
    app.state.proxy_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    log.info("agent-tools hub ready -- facilitator=%s network=%s",
             settings.facilitator_url, settings.network)
    try:
        yield
    finally:
        await app.state.facilitator.aclose()
        await app.state.proxy_client.aclose()
        app.state.db.close()


app = FastAPI(
    title="agent-tools hub",
    description="Free x402 hosting hub — wrap any API into a pay-per-call x402 endpoint. "
                "Pass-through, no platform cut. Apache-2.0.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(PaymentCORSMiddleware)
app.include_router(landing_router)
app.include_router(sellers_router)
app.include_router(gateway_router)
