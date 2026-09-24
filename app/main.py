from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, status

from . import __version__
from .config import Settings
from .llm import LLMUnavailable
from .logging_setup import configure_uvicorn_timestamps
from .schemas import AddRequest, AddResponse, HealthResponse, SearchRequest, SearchResponse
from .service import MemoryService


# Root page HTML for the deployed service. Kept as a module-level constant so the
# FastAPI route stays thin and the page can be tested independently.
ROOT_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentKiln Memory — Evidence-only long-term memory for AI agents</title>
<style>
  :root {
    --bg: #070b14;
    --panel: #0d1526;
    --panel-2: #0a111f;
    --line: #1a2745;
    --line-2: #27395f;
    --text: #f2f5fc;
    --muted: #8b9ab8;
    --accent: #6b9aff;
    --accent-2: #3ee0b8;
    --glow: rgba(107, 154, 255, 0.14);
    --mono: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body {
    font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 0 24px 56px;
    position: relative;
    overflow-x: hidden;
  }
  body::before {
    content: "";
    position: absolute; inset: 0;
    background:
      radial-gradient(800px 400px at 80% -10%, rgba(62, 224, 184, 0.06) 0%, transparent 60%),
      radial-gradient(1100px 600px at 5% -15%, var(--glow) 0%, transparent 55%);
    pointer-events: none;
  }
  body::after {
    content: "";
    position: absolute; inset: 0;
    background-image:
      linear-gradient(rgba(107,154,255,0.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(107,154,255,0.025) 1px, transparent 1px);
    background-size: 56px 56px;
    pointer-events: none;
  }
  .wrap { max-width: 1080px; margin: 0 auto; position: relative; z-index: 1; }
  header.top {
    display: flex; align-items: center; justify-content: space-between;
    padding: 24px 0; gap: 16px;
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .logo {
    width: 38px; height: 38px;
    filter: drop-shadow(0 0 14px rgba(107, 154, 255, 0.35));
  }
  .brand b { font-size: 17px; font-weight: 700; display: block; }
  .brand span { display: block; font-size: 11px; color: var(--muted); font-weight: 400; margin-top: 1px; }
  nav.links { display: flex; gap: 6px; }
  nav.links a {
    color: var(--muted); text-decoration: none; font-size: 13px;
    padding: 8px 14px; border-radius: 7px;
    transition: color 0.2s, background 0.2s;
  }
  nav.links a:hover { color: var(--text); background: var(--panel); }
  .hero { padding: 72px 0 56px; max-width: 780px; }
  .status {
    display: inline-flex; align-items: center; gap: 9px;
    border: 1px solid var(--line-2); border-radius: 999px;
    padding: 7px 16px; font-size: 12px; color: var(--accent-2);
    background: rgba(62, 224, 184, 0.05); margin-bottom: 28px;
  }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-2); animation: pulse 2.4s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(62,224,184,0.4); } 50% { opacity: 0.55; box-shadow: 0 0 0 6px rgba(62,224,184,0); } }
  h1 {
    font-size: clamp(34px, 5.4vw, 52px); font-weight: 780; letter-spacing: -1px;
    line-height: 1.12; margin-bottom: 18px; max-width: 700px;
  }
  h1 .hl {
    background: linear-gradient(120deg, var(--accent) 0%, var(--accent-2) 100%);
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent; color: transparent;
  }
  .tagline { color: var(--muted); font-size: 17px; line-height: 1.7; max-width: 580px; margin-bottom: 34px; }
  .tagline strong { color: var(--text); font-weight: 600; }
  .cta { display: flex; gap: 12px; flex-wrap: wrap; }
  .btn {
    text-decoration: none; font-size: 14px; font-weight: 650;
    padding: 12px 26px; border-radius: 9px;
    transition: transform 0.15s, box-shadow 0.2s, border-color 0.2s;
    display: inline-flex; align-items: center; gap: 8px;
  }
  .btn:hover { transform: translateY(-2px); }
  .btn.primary { background: linear-gradient(135deg, var(--accent) 0%, #4a7dff 100%); color: #06101f; box-shadow: 0 4px 20px rgba(107, 154, 255, 0.25); }
  .btn.primary:hover { box-shadow: 0 6px 28px rgba(107, 154, 255, 0.4); }
  .btn.ghost { color: var(--text); border: 1px solid var(--line-2); }
  .btn.ghost:hover { border-color: var(--accent); }
  .stats {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px; max-width: 640px; margin-top: 40px;
  }
  .stat {
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px;
    padding: 14px 16px;
  }
  .stat b { font-family: var(--mono); font-size: 20px; color: var(--accent-2); display: block; margin-bottom: 2px; }
  .stat span { font-size: 12px; color: var(--muted); }
  .flow {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    margin: 56px 0; padding: 22px 26px;
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px;
  }
  .flow .step {
    display: flex; align-items: center; gap: 10px;
    font-family: var(--mono); font-size: 13px;
  }
  .flow .num {
    width: 26px; height: 26px; border-radius: 6px;
    background: linear-gradient(135deg, rgba(107,154,255,0.15), rgba(62,224,184,0.1));
    border: 1px solid var(--line-2);
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; color: var(--accent); font-weight: 700;
  }
  .flow .arrow { color: var(--line-2); font-size: 16px; }
  .section-title {
    font-size: 12px; text-transform: uppercase; letter-spacing: 2px;
    color: var(--muted); margin-bottom: 18px; font-weight: 600;
  }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; }
  .card {
    background: linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%);
    border: 1px solid var(--line); border-radius: 10px; padding: 22px;
    transition: border-color 0.2s, transform 0.2s;
  }
  .card:hover { border-color: var(--line-2); transform: translateY(-2px); }
  .card .num { font-family: var(--mono); font-size: 11px; color: var(--accent); margin-bottom: 12px; opacity: 0.7; }
  .card h3 { font-size: 15px; margin-bottom: 9px; font-weight: 650; }
  .card p { font-size: 13px; color: var(--muted); line-height: 1.6; }
  .endpoints {
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px;
    overflow: hidden; margin-bottom: 40px;
  }
  .ep-row {
    display: grid; grid-template-columns: 70px 1fr 1fr; align-items: center;
    padding: 15px 22px; border-bottom: 1px solid var(--line);
    font-family: var(--mono); font-size: 13px; gap: 16px;
  }
  .ep-row:last-child { border-bottom: none; }
  .ep-method {
    color: var(--accent-2); font-weight: 700; font-size: 12px;
    background: rgba(62, 224, 184, 0.08); border-radius: 5px;
    padding: 4px 0; text-align: center;
  }
  .ep-method.get { color: var(--accent); background: rgba(107, 154, 255, 0.08); }
  .ep-path { color: var(--text); }
  .ep-desc { color: var(--muted); font-family: "Segoe UI", sans-serif; font-size: 13px; }
  footer {
    border-top: 1px solid var(--line); padding-top: 22px;
    font-size: 12px; color: var(--muted);
    display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  }
  footer a { color: var(--muted); text-decoration: none; }
  footer a:hover { color: var(--text); }
  @media (max-width: 640px) {
    nav.links { display: none; }
    .hero { padding: 32px 0 40px; }
    .ep-row { grid-template-columns: 60px 1fr; }
    .ep-desc { display: none; }
    .stats { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div class="brand">
    <img class="logo" src="/logo.svg" alt="AgentKiln Memory">
    <div><b>AgentKiln Memory</b><span>Evidence-only retrieval</span></div>
  </div>
  <nav class="links">
    <a href="#how">How it works</a>
    <a href="/docs">API Docs</a>
    <a href="/openapi.json">OpenAPI</a>
  </nav>
</header>
<section class="hero">
  <div class="status"><span class="pulse"></span> Service online</div>
  <h1>Long-term memory that returns <span class="hl">evidence</span>, not answers.</h1>
  <p class="tagline">Agent conversations are stored under <strong>strict user isolation</strong>, indexed with hybrid lexical and vector retrieval, and returned as <strong>verbatim source windows</strong>. Every result is auditable, every retrieval is testable.</p>
  <div class="cta">
    <a class="btn primary" href="/docs">Explore the API</a>
    <a class="btn ghost" href="/openapi.json">OpenAPI Schema</a>
  </div>
  <div class="stats">
    <div class="stat"><b>&lt;100ms</b><span>Lexical search latency</span></div>
    <div class="stat"><b>100%</b><span>User isolation</span></div>
    <div class="stat"><b>76</b><span>Tests passing</span></div>
  </div>
</section>
<div class="flow">
  <div class="step"><span class="num">1</span> Add</div>
  <span class="arrow">→</span>
  <div class="step"><span class="num">2</span> Index</div>
  <span class="arrow">→</span>
  <div class="step"><span class="num">3</span> Search</div>
  <span class="arrow">→</span>
  <div class="step"><span class="num">4</span> Evidence</div>
</div>
<section class="section" id="how">
  <div class="section-title">How it works</div>
  <div class="grid">
    <div class="card"><div class="num">01</div><h3>Hybrid retrieval</h3><p>Lexical FTS5 search fused with vector cosine similarity by reciprocal rank. Exact terms and semantic matches both surface.</p></div>
    <div class="card"><div class="num">02</div><h3>Session windows</h3><p>Matched evidence expands to adjacent turns in the same conversation, restoring context a single message loses.</p></div>
    <div class="card"><div class="num">03</div><h3>Temporal ranking</h3><p>Time-aware scoring detects latest and earliest intent, with correction-aware suppression of superseded memories.</p></div>
    <div class="card"><div class="num">04</div><h3>Strict isolation</h3><p>Every memory, index entry, and vector is scoped to the exact caller identity. Cross-user access returns empty.</p></div>
  </div>
</section>
<section class="section">
  <div class="section-title">Endpoints</div>
  <div class="endpoints">
    <div class="ep-row"><span class="ep-method">POST</span><span class="ep-path">/add</span><span class="ep-desc">Store messages with idempotency and conflict detection</span></div>
    <div class="ep-row"><span class="ep-method">POST</span><span class="ep-path">/search</span><span class="ep-desc">Retrieve ranked evidence without generating answers</span></div>
    <div class="ep-row"><span class="ep-method get">GET</span><span class="ep-path">/health</span><span class="ep-desc">Service health, version, and model readiness</span></div>
  </div>
</section>
<footer>
  <span>AgentKiln Memory · Evidence-only long-term memory service</span>
  <span><a href="/docs">Docs</a> · <a href="/openapi.json">OpenAPI</a> · <a href="/health">Health</a></span>
</footer>
</div>
</body>
</html>"""
def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    service = MemoryService(resolved)
    service.initialize()
    app = FastAPI(title="AgentKiln Memory", version=__version__)

    def authorize(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> None:
        if not resolved.api_key:
            return
        supplied = x_api_key
        if authorization:
            prefix, _, value = authorization.partition(" ")
            if prefix.casefold() in {"bearer", "token"}:
                supplied = value
        if not supplied or not hmac.compare_digest(supplied, resolved.api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(version=__version__, llm_mode=resolved.llm_mode, llm_ready=service.llm.ready)

    def handle_add(request: AddRequest) -> AddResponse:
        try:
            service.add(request)
        except LLMUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return AddResponse(
            request_id=request.request_id,
            user_id=request.user_id,
            session_id=request.session_id,
        )

    def handle_search(request: SearchRequest) -> SearchResponse:
        try:
            return SearchResponse(data=service.search(request))
        except LLMUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    app.post("/add", response_model=AddResponse, dependencies=[Depends(authorize)])(handle_add)
    app.post("/search", response_model=SearchResponse, dependencies=[Depends(authorize)])(handle_search)
    app.post("/v1/memory/add", response_model=AddResponse, dependencies=[Depends(authorize)])(handle_add)
    app.post("/v1/memory/search", response_model=SearchResponse, dependencies=[Depends(authorize)])(handle_search)
    return app


from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

configure_uvicorn_timestamps()
app = create_app()
app.docs_url = None
app.redoc_url = None


@app.get('/logo.svg', include_in_schema=False)
def logo():
    from pathlib import Path as _Path
    from fastapi.responses import FileResponse
    return FileResponse(_Path(__file__).parent.parent / "docs" / "assets" / "agentkiln-logo.svg", media_type="image/svg+xml")


@app.get('/', include_in_schema=False)
def root():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(ROOT_PAGE)


@app.get('/docs', include_in_schema=False)
def custom_docs():
    return get_swagger_ui_html(openapi_url=app.openapi_url, title=app.title + ' API')
