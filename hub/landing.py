"""Landing page, health and stats."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

_LANDING = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-tools hub — free x402 hosting</title>
<style>
  body{{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;max-width:46rem;
       margin:3rem auto;padding:0 1.2rem;line-height:1.6;color:#111}}
  code{{background:#f4f4f5;padding:.1rem .35rem;border-radius:3px}}
  h1{{margin-bottom:.2rem}} .muted{{color:#666}}
  pre{{background:#f4f4f5;padding:1rem;border-radius:6px;overflow:auto}}
</style></head><body>
<h1>agent-tools hub</h1>
<p class="muted">Wrap any API into a pay-per-call x402 endpoint. Free, pass-through —
payments settle straight to your wallet, the hub takes no cut.</p>
<h3>List a service</h3>
<pre>curl -X POST {public}/api/v1/submit -H 'content-type: application/json' -d '{{
  "service_slug": "my-api",
  "payout_address": "0xYourBaseWallet",
  "upstream_base_url": "https://api.example.com",
  "price_usdc": 0.01
}}'</pre>
<p>Then lock your upstream to require the <code>X-Hub-Secret</code> we return, and
point clients at <code>{public}/gw/my-api/...</code></p>
<p class="muted"><a href="/api/v1/services">browse live services</a> · <a href="/healthz">health</a></p>
</body></html>"""


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    return HTMLResponse(_LANDING.format(public=settings.public_url.rstrip("/")))


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/stats")
async def stats(request: Request) -> dict:
    return request.app.state.db.stats_24h()
