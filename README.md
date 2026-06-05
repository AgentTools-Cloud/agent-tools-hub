# agent-tools-hub

Free [x402](https://x402.org) hosting hub — wrap **any** API into a pay-per-call
x402 endpoint without writing a line of web3. Pass-through, **no platform cut**:
USDC settles straight to the seller's wallet. Apache-2.0.

Companion to [agent-tools.cloud](https://agent-tools.cloud) (discovery, never
touches funds) and the [facilitator](https://facilitator.agent-tools.cloud)
(verify/settle). This repo is the **gateway**: it puts an x402 paywall in front
of a normal upstream API and reverse-proxies paid requests through.

## How it works

```
buyer ──GET /gw/{slug}/path──▶ hub ──402 + price──▶ buyer
buyer ──retry + X-PAYMENT────▶ hub ──/settle──▶ facilitator ──USDC──▶ seller payTo
                                  └─ proxy ──▶ seller upstream (inject key + X-Hub-Secret)
```

- **Per-call x402** (like proxy402 / MCPay). Subscriptions are a later add-on.
- **Pass-through**: `payTo` is the seller's own address; the hub never holds funds.
- **Anti-freeload**: the hub injects `X-Hub-Secret` into every proxied request;
  the seller's origin must reject anything without it (so buyers can't bypass the
  paywall by hitting the origin directly).
- **Upstream key custody**: the seller's own API key is encrypted at rest
  (Fernet) and injected on proxy; buyers never see it.

## Run it

```bash
git clone git@github.com:AgentTools-Cloud/agent-tools-hub.git
cd agent-tools-hub
cp .env.example .env
python3 scripts/gen_keys.py        # paste FERNET_KEY + ADMIN_TOKEN into .env
chmod 600 .env
docker compose up -d               # or: pip install -e . && uvicorn hub.main:app --port 9300
```

Set `FACILITATOR` to choose who verifies + settles payments (the hub itself
never holds funds). It accepts a preset name or a full URL:

| `FACILITATOR` | facilitator | chain | cost |
|---|---|---|---|
| `x402-org` *(default)* | Coinbase hosted | Base **Sepolia** testnet | none — no key, no gas. Best for dogfood. |
| `cdp` | Coinbase CDP | Base mainnet | needs `FACILITATOR_API_KEY` (CDP JWT) |
| `self` | your own [facilitator](https://github.com/AgentTools-Cloud/facilitator) | Base mainnet | you run it + pay gas |
| `https://…` | any custom facilitator | set `NETWORK` + `USDC_ADDRESS_BASE` | — |

Each preset auto-selects the matching `NETWORK` and USDC contract (testnet vs
mainnet USDC differ), so `clone → up` works out of the box on testnet.

## List a service

```bash
curl -X POST https://hub.agent-tools.cloud/api/v1/submit \
  -H 'content-type: application/json' \
  -d '{
        "service_slug": "my-api",
        "payout_address": "0xYourBaseWallet",
        "upstream_base_url": "https://api.example.com",
        "upstream_auth_header": "Authorization",
        "upstream_auth_value": "Bearer sk-your-upstream-key",
        "price_usdc": 0.01,
        "description": "What my API does"
      }'
```

The response includes a one-time `proxy_secret`. Lock your upstream to require
`X-Hub-Secret: <proxy_secret>`, e.g.:

```js
app.use((req, res, next) =>
  req.headers['x-hub-secret'] === process.env.HUB_SECRET ? next()
    : res.status(403).json({ error: 'direct access denied' }));
```

An admin approves it (probes the upstream, flips it live, optionally mirrors the
listing into agent-tools.cloud):

```bash
curl -X POST https://hub.agent-tools.cloud/api/v1/admin/approve \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'content-type: application/json' -d '{"service_slug": "my-api"}'
```

Buyers then point any x402 client at `https://hub.agent-tools.cloud/gw/my-api/...`.

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/submit` | none | self-serve list a service (status=pending) |
| `POST` | `/api/v1/admin/approve` | admin | probe + go live + mirror to directory |
| `POST` | `/api/v1/admin/reject` | admin | reject a submission |
| `GET`  | `/api/v1/admin/services` | admin | list all (any status) |
| `GET`  | `/api/v1/services` | none | list live services (no secrets) |
| `GET`  | `/api/v1/services/{slug}` | none | one live service (no secrets) |
| `POST` | `/api/v1/needs` | none | post a demand ("I need an API that…") |
| `GET`  | `/api/v1/needs` | none | browse open needs (contact hidden) |
| `ANY`  | `/gw/{slug}/{path}` | x402 | the paywalled reverse proxy |
| `GET`  | `/healthz` · `/stats` | none | ops |

## Layout

```
hub/
├── main.py          FastAPI wiring + payment-header CORS middleware
├── config.py        pydantic-settings (.env)
├── db.py            SQLite: sellers / services / usage_log
├── crypto.py        Fernet encryption of sellers' upstream keys
├── facilitator.py   HTTP client for /verify + /settle
├── x402.py          402 challenge builder (+ extensions.bazaar)
├── gateway.py       per-call x402 reverse proxy
├── sellers.py       self-serve submit + admin approval
└── landing.py       home / health / stats
```

## Design

Pass-through model, competitor landscape (MCPay / proxy402 / Nevermined /
Coinbase Bazaar), and the planned custodial-subscription tier for later are
documented in the private ops notes (`A2A经济/hosting-platform/00_design.md`).
