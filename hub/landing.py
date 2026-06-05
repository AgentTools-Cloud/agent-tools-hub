"""Multi-page site: home, services, needs, list-your-API, about — plus health/stats.

Server-rendered shell (shared nav/footer/CSS); dynamic data is fetched client-side
from the JSON API. User-supplied text is HTML-escaped in JS to avoid stored XSS.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

GITHUB = "https://github.com/AgentTools-Cloud/agent-tools-hub"
DIRECTORY = "https://agent-tools.cloud"

_CSS = """
:root{--bg:#fff;--fg:#0f172a;--muted:#64748b;--line:#e2e8f0;--brand:#4f46e5;
--brand2:#7c3aed;--soft:#f8fafc;--code:#0b1020;--ok:#16a34a}
*{box-sizing:border-box}
body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
color:var(--fg);background:var(--bg);line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:64rem;margin:0 auto;padding:0 1.25rem}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
code{background:var(--soft);padding:.12rem .4rem;border-radius:4px;font-size:.9em}
nav{position:sticky;top:0;background:rgba(255,255,255,.85);backdrop-filter:blur(8px);
border-bottom:1px solid var(--line);z-index:10}
nav .wrap{display:flex;align-items:center;gap:1.1rem;height:3.5rem}
.logo{font-weight:700;font-size:1.05rem;letter-spacing:-.01em}
.logo b{background:linear-gradient(90deg,var(--brand),var(--brand2));-webkit-background-clip:text;
background-clip:text;color:transparent}
nav .links{margin-left:auto;display:flex;gap:1.05rem;align-items:center;font-size:.92rem}
nav .links a{color:var(--muted)}nav .links a.on{color:var(--fg);font-weight:600}
.btn{display:inline-block;background:var(--brand);color:#fff!important;padding:.55rem .95rem;
border-radius:8px;font-weight:600;font-size:.92rem;border:1px solid var(--brand);cursor:pointer}
.btn:hover{background:#4338ca;text-decoration:none}
.btn.ghost{background:#fff;color:var(--brand)!important}
.hero{padding:4rem 0 2.4rem;text-align:center}
.hero h1{font-size:2.6rem;line-height:1.1;letter-spacing:-.03em;margin:.3rem 0 1rem}
.hero h1 span{background:linear-gradient(90deg,var(--brand),var(--brand2));-webkit-background-clip:text;
background-clip:text;color:transparent}
.hero p.lead{font-size:1.16rem;color:var(--muted);max-width:42rem;margin:0 auto 1.5rem}
.cta{display:flex;gap:.75rem;justify-content:center;flex-wrap:wrap}
.badges{display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap;margin-top:1.5rem}
.badge{font-size:.82rem;color:var(--muted);background:var(--soft);border:1px solid var(--line);
padding:.3rem .7rem;border-radius:999px}.badge b{color:var(--ok)}
.stat{margin-top:1.3rem;font-size:.9rem;color:var(--muted)}.stat b{color:var(--fg)}
.page{padding:2.6rem 0}
h2{font-size:1.55rem;letter-spacing:-.02em;margin:0 0 .35rem}
.sub{color:var(--muted);margin:0 0 1.6rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1.6rem}
.tile{display:block;border:1px solid var(--line);border-radius:14px;padding:1.4rem;background:#fff;
color:inherit}
.tile:hover{border-color:var(--brand);text-decoration:none;box-shadow:0 4px 20px rgba(79,70,229,.07)}
.tile h3{margin:.2rem 0 .35rem;font-size:1.2rem}
.tile p{margin:0;color:var(--muted)}
.tile .arrow{color:var(--brand);font-weight:600;margin-top:.7rem;display:inline-block}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-top:1.4rem}
.card{border:1px solid var(--line);border-radius:12px;padding:1.2rem;background:#fff}
.card .n{display:inline-flex;width:1.7rem;height:1.7rem;align-items:center;justify-content:center;
border-radius:7px;background:var(--brand);color:#fff;font-weight:700;font-size:.9rem;margin-bottom:.6rem}
.card h3{margin:.1rem 0 .4rem;font-size:1.05rem}.card p{margin:0;color:var(--muted);font-size:.94rem}
pre.block{background:var(--code);color:#e5e7eb;padding:1.1rem 1.2rem;border-radius:10px;overflow:auto;
font-size:.85rem;line-height:1.55}
.note{background:var(--soft);border-left:3px solid var(--brand);padding:.8rem 1rem;border-radius:0 8px 8px 0;
font-size:.92rem;color:#334155;margin:1rem 0}
.list{display:flex;flex-direction:column;gap:.5rem;margin-top:.6rem}
.item{border:1px solid var(--line);border-radius:9px;padding:.75rem .9rem;display:flex;
justify-content:space-between;align-items:center;gap:1rem;font-size:.93rem}
.item .price{color:var(--brand);font-weight:600;white-space:nowrap}
.empty{color:var(--muted);font-size:.92rem}
form.box{border:1px solid var(--line);border-radius:12px;padding:1.3rem;background:#fff;margin-top:1.2rem}
label{display:block;font-size:.85rem;font-weight:600;margin:.7rem 0 .25rem}
input,textarea{width:100%;padding:.55rem .7rem;border:1px solid var(--line);border-radius:8px;
font:inherit;font-size:.93rem}
textarea{min-height:4.5rem;resize:vertical}
.row{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.muted{color:var(--muted)}
.result{margin-top:1rem;padding:.9rem 1rem;border-radius:9px;font-size:.9rem;display:none}
.result.ok{background:#f0fdf4;border:1px solid #bbf7d0;color:#166534;display:block}
.result.err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;display:block}
details{border:1px solid var(--line);border-radius:10px;padding:.4rem 1rem;margin-bottom:.6rem}
details summary{cursor:pointer;font-weight:600;padding:.5rem 0}details p{color:var(--muted);margin:.2rem 0 .8rem}
footer{border-top:1px solid var(--line);padding:2rem 0;color:var(--muted);font-size:.88rem;margin-top:1rem}
footer .wrap{display:flex;gap:1rem;flex-wrap:wrap;align-items:center}
footer .flinks{margin-left:auto;display:flex;gap:1rem}
@media(max-width:680px){.hero h1{font-size:2rem}.grid3,.two,.row{grid-template-columns:1fr}
nav .links a:not(.btn){display:none}}
"""

_NAV_ITEMS = [
    ("/", "Home", "home"),
    ("/services", "Services", "services"),
    ("/requests", "Requests", "requests"),
    ("/about", "How it works", "about"),
]

_ESC_JS = """
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
"""


def _shell(active: str, body: str, script: str = "") -> str:
    links = "".join(
        '<a href="%s"%s>%s</a>' % (href, ' class="on"' if k == active else "", label)
        for href, label, k in _NAV_ITEMS
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>agent-tools hub — the x402 marketplace</title>"
        "<meta name=\"description\" content=\"A two-sided x402 marketplace: list an API as a "
        "pay-per-call endpoint, or post what you need. Free, pass-through, open source.\">"
        "<style>" + _CSS + "</style></head><body>"
        "<nav><div class=\"wrap\"><div class=\"logo\">agent-tools <b>hub</b></div>"
        "<div class=\"links\">" + links +
        "<a href=\"__GITHUB__\" target=\"_blank\" rel=\"noopener\">GitHub</a>"
        "<a class=\"btn ghost\" href=\"/list\">List your API</a>"
        "<a class=\"btn\" href=\"/requests\">Request a Service</a></div></div></nav>"
        + body +
        "<footer><div class=\"wrap\"><div>agent-tools <b>hub</b> · the x402 marketplace · Apache-2.0</div>"
        "<div class=\"flinks\"><a href=\"__GITHUB__\" target=\"_blank\" rel=\"noopener\">GitHub</a>"
        "<a href=\"__DIRECTORY__\" target=\"_blank\" rel=\"noopener\">Directory</a>"
        "<a href=\"/services\">Services</a><a href=\"/requests\">Requests</a><a href=\"/healthz\">Health</a>"
        "</div></div></footer>"
        "<script>" + _ESC_JS + script + "</script></body></html>"
    )


# ---------- page bodies ----------

_HOME = """
<header class="hero"><div class="wrap">
  <h1>The marketplace for<br><span>agent-payable APIs</span></h1>
  <p class="lead">List an existing API as a pay-per-call
  <a href="https://x402.org" target="_blank" rel="noopener">x402</a> endpoint — or post what you wish
  existed. Agents pay in USDC per request; the money lands <b>straight in the seller's wallet</b>.</p>
  <div class="cta">
    <a class="btn" href="/list">List a service &rarr;</a>
    <a class="btn ghost" href="/requests">Request a service &rarr;</a>
  </div>
  <div class="badges">
    <span class="badge"><b>Free</b> — no platform cut</span>
    <span class="badge">Pass-through settlement</span>
    <span class="badge">Open source</span>
    <span class="badge">Built on x402</span>
  </div>
  <div class="stat" id="stat"></div>
</div></header>

<section class="page"><div class="wrap">
  <div class="two">
    <a class="tile" href="/list"><h3>I have an API &rarr;</h3>
      <p>Wrap it into a paid x402 endpoint in minutes. No web3 code. Money settles to your wallet.</p>
      <span class="arrow">List a service</span></a>
    <a class="tile" href="/requests"><h3>I need an API &rarr;</h3>
      <p>Post what you'd pay for. Surface real demand so builders know what to ship.</p>
      <span class="arrow">Request a service</span></a>
  </div>
</div></section>

<section class="page" style="border-top:1px solid var(--line)"><div class="wrap">
  <h2>How it works</h2>
  <p class="sub">You keep running your API. We put a payment wall in front and reverse-proxy paid calls through.</p>
  <div class="grid3">
    <div class="card"><span class="n">1</span><h3>Submit your API</h3>
      <p>Upstream URL, a price, and the wallet that should receive payment.</p></div>
    <div class="card"><span class="n">2</span><h3>We wrap it in x402</h3>
      <p>No payment &rarr; <code>402</code> + price. Caller pays USDC, we verify, then proxy.</p></div>
    <div class="card"><span class="n">3</span><h3>You get paid</h3>
      <p>USDC settles directly to your wallet on every call. The hub never holds funds.</p></div>
  </div>
  <p style="margin-top:1.2rem"><a href="/about">Read the full how-it-works &amp; FAQ &rarr;</a></p>
</div></section>
"""

_HOME_JS = """
fetch('/stats').then(r=>r.json()).then(s=>{
  document.getElementById('stat').innerHTML='<b>'+(s.live_services||0)+'</b> live services · <b>'
  +(s.open_needs||0)+'</b> open needs · <b>'+(s.calls_24h||0)+'</b> calls in 24h';}).catch(()=>{});
"""

_SERVICES = """
<section class="page"><div class="wrap">
  <h2>Live services</h2>
  <p class="sub">Paid APIs available right now. Any x402 client can call them — hit the gateway URL,
  pay on <code>402</code>, get your result.</p>
  <div id="svc" class="list"><div class="empty">Loading…</div></div>
  <p style="margin-top:1.4rem"><a class="btn" href="/list">List your API &rarr;</a></p>
</div></section>
"""

_SERVICES_JS = """
fetch('/api/v1/services').then(r=>r.json()).then(list=>{
  var el=document.getElementById('svc');
  if(!list.length){el.innerHTML='<div class="empty">No live services yet — be the first.</div>';return;}
  el.innerHTML=list.map(function(s){return '<div class="item"><div><b>'+esc(s.slug)+'</b>'
    +(s.description?' — <span class="muted">'+esc(s.description)+'</span>':'')
    +'</div><div class="price">$'+esc(s.price_usdc)+'/call</div></div>';}).join('');
}).catch(()=>{document.getElementById('svc').innerHTML='<div class="empty">Could not load services.</div>';});
"""

_NEEDS = """
<section class="page"><div class="wrap">
  <h2>Request a service</h2>
  <p class="sub">Can't find the API you want? Tell builders what you'd pay for. Supply follows demand.</p>

  <form class="box" id="needForm">
    <label>Title *</label>
    <input name="title" required maxlength="120" placeholder="e.g. Cheap self-hosted OCR for academic PDFs">
    <label>Description</label>
    <textarea name="description" maxlength="2000" placeholder="What it should do, quality bar, constraints…"></textarea>
    <div class="row">
      <div><label>Category</label><input name="category" placeholder="document / search / inference…"></div>
      <div><label>Budget (USD, optional)</label><input name="budget_usd" type="number" step="0.01" min="0" placeholder="50"></div>
    </div>
    <label>Contact (kept private, optional)</label>
    <input name="contact" maxlength="200" placeholder="you@example.com — not shown on the public board">
    <div style="margin-top:1rem"><button class="btn" type="submit">Submit request</button></div>
    <div class="result" id="needResult"></div>
  </form>

  <h2 style="margin-top:2.4rem">Open requests</h2>
  <div id="needs" class="list"><div class="empty">Loading…</div></div>
</div></section>
"""

_NEEDS_JS = """
function loadNeeds(){
  fetch('/api/v1/needs').then(r=>r.json()).then(list=>{
    var el=document.getElementById('needs');
    if(!list.length){el.innerHTML='<div class="empty">No open requests yet — post the first.</div>';return;}
    el.innerHTML=list.map(function(n){return '<div class="item"><div><b>'+esc(n.title)+'</b>'
      +(n.description?' — <span class="muted">'+esc(n.description)+'</span>':'')
      +'</div>'+(n.budget_usd!=null?'<div class="price">~$'+esc(n.budget_usd)+'</div>':'')+'</div>';}).join('');
  }).catch(()=>{document.getElementById('needs').innerHTML='<div class="empty">Could not load needs.</div>';});
}
loadNeeds();
document.getElementById('needForm').addEventListener('submit',function(e){
  e.preventDefault();
  var f=e.target, r=document.getElementById('needResult');
  var body={title:f.title.value.trim(),description:f.description.value.trim()||null,
    category:f.category.value.trim()||null,
    budget_usd:f.budget_usd.value?parseFloat(f.budget_usd.value):null,
    contact:f.contact.value.trim()||null};
  fetch('/api/v1/needs',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)})
   .then(res=>res.json().then(j=>({ok:res.ok,j:j})))
   .then(function(o){
     if(o.ok){r.className='result ok';r.textContent='Posted! Your request is now on the board.';f.reset();loadNeeds();}
     else{r.className='result err';r.textContent='Error: '+(o.j.detail||JSON.stringify(o.j));}
   }).catch(()=>{r.className='result err';r.textContent='Network error.';});
});
"""

_LIST = """
<section class="page"><div class="wrap">
  <h2>List your API</h2>
  <p class="sub">Register an existing API as a paid x402 endpoint. Approval flips it live and can mirror it
  into the <a href="__DIRECTORY__" target="_blank" rel="noopener">agent-tools.cloud</a> directory.</p>

  <form class="box" id="listForm">
    <div class="row">
      <div><label>Service slug *</label><input name="service_slug" required placeholder="my-api"></div>
      <div><label>Price per call (USDC) *</label><input name="price_usdc" type="number" step="0.0001" min="0" required placeholder="0.01"></div>
    </div>
    <label>Upstream base URL *</label>
    <input name="upstream_base_url" required placeholder="https://api.example.com">
    <div class="row">
      <div><label>Payout address (Base) *</label><input name="payout_address" required placeholder="0xYourWallet"></div>
      <div><label>Category</label><input name="category" placeholder="document / search…"></div>
    </div>
    <div class="row">
      <div><label>Upstream auth header</label><input name="upstream_auth_header" placeholder="Authorization"></div>
      <div><label>Upstream auth value</label><input name="upstream_auth_value" placeholder="Bearer sk-… (encrypted at rest)"></div>
    </div>
    <label>Description</label>
    <textarea name="description" placeholder="What your API does"></textarea>
    <div style="margin-top:1rem"><button class="btn" type="submit">Submit for review</button></div>
    <div class="result" id="listResult"></div>
  </form>

  <div class="note"><b>Anti-freeload:</b> on submit you get a one-time <code>proxy_secret</code>. Lock your
  upstream to require an <code>X-Hub-Secret</code> header equal to it, so callers can't bypass the paywall
  by hitting your origin directly. Your upstream key is encrypted at rest and injected on proxy — buyers
  never see it. After approval, callers use <code>__PUBLIC__/gw/&lt;slug&gt;/&lt;path&gt;</code>.</div>

  <p class="muted">Prefer the CLI?</p>
  <pre class="block">curl -X POST __PUBLIC__/api/v1/submit -H 'content-type: application/json' -d '{
  "service_slug": "my-api", "payout_address": "0xYourWallet",
  "upstream_base_url": "https://api.example.com", "price_usdc": 0.01 }'</pre>
</div></section>
"""

_LIST_JS = """
document.getElementById('listForm').addEventListener('submit',function(e){
  e.preventDefault();
  var f=e.target, r=document.getElementById('listResult');
  var body={service_slug:f.service_slug.value.trim(),
    price_usdc:parseFloat(f.price_usdc.value),
    upstream_base_url:f.upstream_base_url.value.trim(),
    payout_address:f.payout_address.value.trim(),
    category:f.category.value.trim()||null,
    upstream_auth_header:f.upstream_auth_header.value.trim()||null,
    upstream_auth_value:f.upstream_auth_value.value.trim()||null,
    description:f.description.value.trim()||null};
  fetch('/api/v1/submit',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)})
   .then(res=>res.json().then(j=>({ok:res.ok,j:j})))
   .then(function(o){
     if(o.ok){r.className='result ok';
       r.innerHTML='Submitted &amp; pending review. <b>Save your proxy_secret now</b> (shown once): <code>'
       +esc(o.j.proxy_secret)+'</code>';f.reset();}
     else{r.className='result err';r.textContent='Error: '+(o.j.detail||JSON.stringify(o.j));}
   }).catch(()=>{r.className='result err';r.textContent='Network error.';});
});
"""

_ABOUT = """
<section class="page"><div class="wrap">
  <h2>How it works</h2>
  <p class="sub">A two-sided x402 marketplace. We never touch your money.</p>
  <pre class="block">buyer ──GET /gw/{slug}/path──▶ hub ──402 + price──▶ buyer
buyer ──retry + X-PAYMENT────▶ hub ──settle──▶ facilitator ──USDC──▶ seller wallet
                                 └─ proxy ──▶ seller upstream (inject key + X-Hub-Secret)</pre>
  <div class="grid3">
    <div class="card"><h3>No platform cut</h3><p>Pass-through settlement: 100% of each payment goes to the
      seller's wallet. We don't custody funds.</p></div>
    <div class="card"><h3>No web3 code</h3><p>Bring a normal REST API. We handle 402 challenges, signature
      verification and settlement.</p></div>
    <div class="card"><h3>Open source</h3><p>Apache-2.0. Audit it or self-host. Point it at any facilitator.</p></div>
  </div>

  <h2 style="margin-top:2.2rem">FAQ</h2>
  <details><summary>Do you hold my money?</summary><p>No. Payments settle directly to your <code>payTo</code>
    wallet via an x402 facilitator. The hub is only the coordinator and takes no cut.</p></details>
  <details><summary>What chains / tokens?</summary><p>USDC over x402. The default facilitator runs on Base;
    the network is configurable per deployment.</p></details>
  <details><summary>Do I have to give you my upstream API key?</summary><p>If your upstream needs auth, yes —
    it's encrypted at rest and injected only when proxying paid calls. Rotate or revoke anytime; every
    proxied call is logged for you.</p></details>
  <details><summary>How is this different from proxy402 or MCPay?</summary><p>Same per-call x402 wrapping,
    plus a demand board and directory distribution through agent-tools.cloud — and you can point it at any
    facilitator (hosted, CDP, or your own).</p></details>
</div></section>
"""


def _render(active: str, body: str, script: str, public: str) -> HTMLResponse:
    html = (_shell(active, body, script)
            .replace("__PUBLIC__", public)
            .replace("__GITHUB__", GITHUB)
            .replace("__DIRECTORY__", DIRECTORY))
    return HTMLResponse(html)


def _public(request: Request) -> str:
    return request.app.state.settings.public_url.rstrip("/")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return _render("home", _HOME, _HOME_JS, _public(request))


@router.get("/services", response_class=HTMLResponse)
async def services_page(request: Request) -> HTMLResponse:
    return _render("services", _SERVICES, _SERVICES_JS, _public(request))


@router.get("/requests", response_class=HTMLResponse)
async def requests_page(request: Request) -> HTMLResponse:
    return _render("requests", _NEEDS, _NEEDS_JS, _public(request))


@router.get("/needs")
async def needs_redirect() -> RedirectResponse:
    return RedirectResponse(url="/requests", status_code=308)


@router.get("/list", response_class=HTMLResponse)
async def list_page(request: Request) -> HTMLResponse:
    return _render("list", _LIST, _LIST_JS, _public(request))


@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request) -> HTMLResponse:
    return _render("about", _ABOUT, "", _public(request))


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/stats")
async def stats(request: Request) -> dict:
    return request.app.state.db.stats_24h()
