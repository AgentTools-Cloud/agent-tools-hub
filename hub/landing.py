"""Landing page, health and stats."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-tools hub — turn any API into an agent-payable x402 endpoint</title>
<meta name="description" content="Wrap any API into a pay-per-call x402 endpoint in minutes. Free, open-source, pass-through — payments settle straight to your wallet. No platform cut.">
<style>
  :root{
    --bg:#ffffff; --fg:#0f172a; --muted:#64748b; --line:#e2e8f0;
    --brand:#4f46e5; --brand2:#7c3aed; --soft:#f8fafc; --code:#0b1020; --ok:#16a34a;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       color:var(--fg);background:var(--bg);line-height:1.6;-webkit-font-smoothing:antialiased}
  a{color:var(--brand);text-decoration:none}
  a:hover{text-decoration:underline}
  .wrap{max-width:64rem;margin:0 auto;padding:0 1.25rem}
  code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  code{background:var(--soft);padding:.12rem .4rem;border-radius:4px;font-size:.9em}
  nav{position:sticky;top:0;background:rgba(255,255,255,.85);backdrop-filter:blur(8px);
      border-bottom:1px solid var(--line);z-index:10}
  nav .wrap{display:flex;align-items:center;gap:1.25rem;height:3.5rem}
  .logo{font-weight:700;font-size:1.05rem;letter-spacing:-.01em}
  .logo b{background:linear-gradient(90deg,var(--brand),var(--brand2));-webkit-background-clip:text;
          background-clip:text;color:transparent}
  nav .links{margin-left:auto;display:flex;gap:1.1rem;align-items:center;font-size:.92rem}
  nav .links a{color:var(--muted)}
  .btn{display:inline-block;background:var(--brand);color:#fff!important;padding:.55rem .95rem;
       border-radius:8px;font-weight:600;font-size:.92rem;border:1px solid var(--brand)}
  .btn:hover{background:#4338ca;text-decoration:none}
  .btn.ghost{background:#fff;color:var(--brand)!important}
  .hero{padding:4.5rem 0 2.5rem;text-align:center}
  .hero h1{font-size:2.7rem;line-height:1.1;letter-spacing:-.03em;margin:.4rem 0 1rem}
  .hero h1 span{background:linear-gradient(90deg,var(--brand),var(--brand2));-webkit-background-clip:text;
                background-clip:text;color:transparent}
  .hero p.lead{font-size:1.18rem;color:var(--muted);max-width:42rem;margin:0 auto 1.6rem}
  .cta{display:flex;gap:.75rem;justify-content:center;flex-wrap:wrap}
  .badges{display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap;margin-top:1.6rem}
  .badge{font-size:.82rem;color:var(--muted);background:var(--soft);border:1px solid var(--line);
         padding:.3rem .7rem;border-radius:999px}
  .badge b{color:var(--ok)}
  .stat{margin-top:1.4rem;font-size:.9rem;color:var(--muted)}
  .stat b{color:var(--fg)}
  section{padding:3rem 0;border-top:1px solid var(--line)}
  section h2{font-size:1.6rem;letter-spacing:-.02em;margin:0 0 .4rem}
  section .sub{color:var(--muted);margin:0 0 1.8rem}
  .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
  .card{border:1px solid var(--line);border-radius:12px;padding:1.2rem;background:#fff}
  .card .n{display:inline-flex;width:1.7rem;height:1.7rem;align-items:center;justify-content:center;
           border-radius:7px;background:var(--brand);color:#fff;font-weight:700;font-size:.9rem;margin-bottom:.6rem}
  .card h3{margin:.1rem 0 .4rem;font-size:1.05rem}
  .card p{margin:0;color:var(--muted);font-size:.94rem}
  pre.block{background:var(--code);color:#e5e7eb;padding:1.1rem 1.2rem;border-radius:10px;
            overflow:auto;font-size:.86rem;line-height:1.55}
  .note{background:var(--soft);border-left:3px solid var(--brand);padding:.8rem 1rem;border-radius:0 8px 8px 0;
        font-size:.92rem;color:#334155;margin-top:1rem}
  .feat{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem}
  .feat .item{display:flex;gap:.7rem;align-items:flex-start}
  .feat .tick{color:var(--ok);font-weight:700;flex:none}
  .feat h4{margin:0 0 .15rem;font-size:1rem}
  .feat p{margin:0;color:var(--muted);font-size:.92rem}
  details{border:1px solid var(--line);border-radius:10px;padding:.4rem 1rem;margin-bottom:.6rem}
  details summary{cursor:pointer;font-weight:600;padding:.5rem 0}
  details p{color:var(--muted);margin:.2rem 0 .8rem}
  #svc{display:flex;flex-direction:column;gap:.5rem}
  .svc{border:1px solid var(--line);border-radius:9px;padding:.7rem .9rem;display:flex;
       justify-content:space-between;align-items:center;gap:1rem;font-size:.92rem}
  .svc .price{color:var(--brand);font-weight:600;white-space:nowrap}
  .empty{color:var(--muted);font-size:.92rem}
  footer{border-top:1px solid var(--line);padding:2rem 0;color:var(--muted);font-size:.88rem}
  footer .wrap{display:flex;gap:1rem;flex-wrap:wrap;align-items:center}
  footer .links{margin-left:auto;display:flex;gap:1rem}
  @media(max-width:680px){
    .hero h1{font-size:2rem}.grid3{grid-template-columns:1fr}.feat{grid-template-columns:1fr}
    nav .links a:not(.btn){display:none}
  }
</style></head><body>

<nav><div class="wrap">
  <div class="logo">agent-tools <b>hub</b></div>
  <div class="links">
    <a href="#how">How it works</a>
    <a href="#sellers">List a service</a>
    <a href="#needs">Post a need</a>
    <a href="__GITHUB__" target="_blank" rel="noopener">GitHub</a>
    <a class="btn" href="#sellers">List your API</a>
  </div>
</div></nav>

<header class="hero"><div class="wrap">
  <h1>The marketplace for<br><span>agent-payable APIs</span></h1>
  <p class="lead">List an existing API as a pay-per-call <a href="https://x402.org" target="_blank" rel="noopener">x402</a>
  endpoint &mdash; or post what you wish existed. Agents pay in USDC per request, and the money lands
  <b>straight in the seller's wallet</b>.</p>
  <div class="cta">
    <a class="btn" href="#sellers">List a service &rarr;</a>
    <a class="btn ghost" href="#needs">Post a need &rarr;</a>
  </div>
  <div class="badges">
    <span class="badge"><b>Free</b> &mdash; no platform cut</span>
    <span class="badge">Pass-through settlement</span>
    <span class="badge">Open source</span>
    <span class="badge">Built on x402</span>
  </div>
  <div class="stat" id="stat"></div>
</div></header>

<section id="how"><div class="wrap">
  <h2>How it works</h2>
  <p class="sub">You keep running your API. We put a payment wall in front and reverse-proxy paid calls through.</p>
  <div class="grid3">
    <div class="card"><span class="n">1</span><h3>Submit your API</h3>
      <p>Give us your upstream URL, a price, and the wallet that should receive payment.</p></div>
    <div class="card"><span class="n">2</span><h3>We wrap it in x402</h3>
      <p>Callers hit a new URL. No payment &rarr; <code>402</code> + price. They pay USDC, we verify, then proxy.</p></div>
    <div class="card"><span class="n">3</span><h3>You get paid</h3>
      <p>USDC settles directly to your wallet on every call. The hub never holds your funds.</p></div>
  </div>
</div></section>

<section id="sellers"><div class="wrap">
  <h2>List a service</h2>
  <p class="sub">One request to register. Approval flips it live and (optionally) lists it in the
  <a href="__DIRECTORY__" target="_blank" rel="noopener">agent-tools.cloud</a> directory.</p>
  <pre class="block">curl -X POST __PUBLIC__/api/v1/submit \\
  -H 'content-type: application/json' \\
  -d '{
    "service_slug": "my-api",
    "payout_address": "0xYourBaseWallet",
    "upstream_base_url": "https://api.example.com",
    "upstream_auth_header": "Authorization",
    "upstream_auth_value": "Bearer sk-your-upstream-key",
    "price_usdc": 0.01,
    "description": "What my API does"
  }'</pre>
  <div class="note"><b>Anti-freeload:</b> the response returns a one-time <code>proxy_secret</code>.
  Lock your upstream to require an <code>X-Hub-Secret</code> header equal to it, so callers can't bypass the
  paywall by hitting your origin directly. Your upstream API key is encrypted at rest and injected on
  proxy — buyers never see it.</div>
  <p style="margin-top:1rem">After approval, callers use <code>__PUBLIC__/gw/my-api/&lt;path&gt;</code>.</p>
</div></section>

<section id="buyers"><div class="wrap">
  <h2>For buyers (agents)</h2>
  <p class="sub">Any x402 client works. Hit the gateway URL; on <code>402</code>, pay and retry.</p>
  <pre class="block"># with the x402 fetch/axios wrapper, payment + retry is automatic
curl __PUBLIC__/gw/my-api/search?q=hello        <span style="color:#94a3b8"># 402 + price</span>
# &rarr; client signs USDC payment, retries with X-PAYMENT &rarr; 200 + result</pre>
  <h3 style="margin:1.6rem 0 .6rem;font-size:1.05rem">Live services</h3>
  <div id="svc"><div class="empty">Loading&hellip;</div></div>
</div></section>

<section id="needs"><div class="wrap">
  <h2>Post a need</h2>
  <p class="sub">Can't find the API you want? Tell builders what you'd pay for. Supply follows demand &mdash;
  this board surfaces real intent so sellers know what to ship.</p>
  <pre class="block">curl -X POST __PUBLIC__/api/v1/needs \\
  -H 'content-type: application/json' \\
  -d '{
    "title": "Cheap self-hosted OCR for academic PDFs",
    "description": "Per-page price target &lt; $0.002, LaTeX output",
    "category": "document",
    "budget_usd": 50,
    "contact": "you@example.com"
  }'</pre>
  <h3 style="margin:1.6rem 0 .6rem;font-size:1.05rem">Open needs</h3>
  <div id="needs-list"><div class="empty">Loading&hellip;</div></div>
</div></section>

<section><div class="wrap">
  <h2>Why agent-tools hub</h2>
  <p class="sub">Everything proxy402 / MCPay give you, plus directory distribution — and we never touch your money.</p>
  <div class="feat">
    <div class="item"><span class="tick">&#10003;</span><div><h4>No platform cut</h4>
      <p>Pass-through settlement: 100% of each payment goes to your wallet. We don't custody funds.</p></div></div>
    <div class="item"><span class="tick">&#10003;</span><div><h4>No web3 code</h4>
      <p>You bring a normal REST API. We handle 402 challenges, signature verification and settlement.</p></div></div>
    <div class="item"><span class="tick">&#10003;</span><div><h4>Directory distribution</h4>
      <p>Approved services can be mirrored into the agent-tools.cloud discovery index for agents to find.</p></div></div>
    <div class="item"><span class="tick">&#10003;</span><div><h4>Open source</h4>
      <p>Apache-2.0. Audit it, or self-host the whole thing. Choose your own facilitator.</p></div></div>
  </div>
</div></section>

<section><div class="wrap">
  <h2>FAQ</h2>
  <details><summary>Do you hold my money?</summary>
    <p>No. Payments settle directly to your <code>payTo</code> wallet via an x402 facilitator. The hub
    is only the coordinator — it never custodies funds and takes no cut.</p></details>
  <details><summary>What chains / tokens?</summary>
    <p>USDC over x402. The default facilitator runs on Base; the network is configurable per deployment.</p></details>
  <details><summary>Do I have to give you my upstream API key?</summary>
    <p>If your upstream needs auth, yes — it's encrypted at rest and injected only when proxying paid calls.
    You can rotate or revoke it anytime, and every proxied call is logged for you to audit.</p></details>
  <details><summary>How is this different from proxy402 or MCPay?</summary>
    <p>Same per-call x402 wrapping, but approved services get distribution through the agent-tools.cloud
    directory, and you can point it at any facilitator (hosted, CDP, or your own).</p></details>
</div></section>

<footer><div class="wrap">
  <div>agent-tools <b>hub</b> · free x402 hosting · Apache-2.0</div>
  <div class="links">
    <a href="__GITHUB__" target="_blank" rel="noopener">GitHub</a>
    <a href="__DIRECTORY__" target="_blank" rel="noopener">Directory</a>
    <a href="/api/v1/services">API</a>
    <a href="/healthz">Health</a>
  </div>
</div></footer>

<script>
(async () => {
  try {
    const r = await fetch('/stats'); const s = await r.json();
    document.getElementById('stat').innerHTML =
      '<b>' + (s.live_services||0) + '</b> live services &middot; <b>' + (s.open_needs||0)
      + '</b> open needs &middot; <b>' + (s.calls_24h||0) + '</b> calls in 24h';
  } catch (e) {}
  try {
    const r = await fetch('/api/v1/services'); const list = await r.json();
    const el = document.getElementById('svc');
    if (!list.length) { el.innerHTML = '<div class="empty">No live services yet &mdash; be the first.</div>'; }
    else el.innerHTML = list.map(s =>
      '<div class="svc"><div><b>' + (s.slug||'') + '</b>'
      + (s.description ? ' &mdash; <span style="color:#64748b">' + s.description + '</span>' : '')
      + '</div><div class="price">$' + (s.price_usdc) + '/call</div></div>'
    ).join('');
  } catch (e) {
    document.getElementById('svc').innerHTML = '<div class="empty">Could not load services.</div>';
  }
  try {
    const r = await fetch('/api/v1/needs'); const list = await r.json();
    const el = document.getElementById('needs-list');
    if (!list.length) { el.innerHTML = '<div class="empty">No open needs yet &mdash; post the first.</div>'; }
    else el.innerHTML = list.map(n =>
      '<div class="svc"><div><b>' + (n.title||'') + '</b>'
      + (n.description ? ' &mdash; <span style="color:#64748b">' + n.description + '</span>' : '')
      + '</div>' + (n.budget_usd!=null ? '<div class="price">~$' + n.budget_usd + '</div>' : '') + '</div>'
    ).join('');
  } catch (e) {
    document.getElementById('needs-list').innerHTML = '<div class="empty">Could not load needs.</div>';
  }
})();
</script>
</body></html>"""


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    public = settings.public_url.rstrip("/")
    html = (_PAGE
            .replace("__PUBLIC__", public)
            .replace("__GITHUB__", "https://github.com/AgentTools-Cloud/agent-tools-hub")
            .replace("__DIRECTORY__", "https://agent-tools.cloud"))
    return HTMLResponse(html)


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/stats")
async def stats(request: Request) -> dict:
    return request.app.state.db.stats_24h()
