from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, status

from . import __version__
from .config import Settings
from .llm import LLMUnavailable
from .schemas import AddRequest, AddResponse, HealthResponse, SearchRequest, SearchResponse
from .service import MemoryService


# Root page HTML for the deployed service. Kept as a module-level constant so the
# FastAPI route stays thin and the page can be tested independently.
ROOT_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentKiln Memory</title>
<style>
  :root {
    --bg: #0a0f1c;
    --panel: #101828;
    --panel-2: #0d1526;
    --line: #1e2c4a;
    --text: #eef2fb;
    --muted: #8b9ab8;
    --accent: #5b8cff;
    --accent-2: #35d6b0;
    --mono: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Segoe UI", system-ui, sans-serif;
    background:
      radial-gradient(900px 500px at 85% -10%, rgba(53, 214, 176, 0.07) 0%, transparent 60%),
      radial-gradient(1000px 600px at 10% -20%, rgba(91, 140, 255, 0.12) 0%, transparent 55%),
      var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 0 24px 48px;
  }
  .top {
    max-width: 1080px; margin: 0 auto; padding: 22px 0;
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .logo {
    width: 34px; height: 34px; border-radius: 8px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 16px; color: #06101f;
  }
  .brand b { font-size: 16px; }
  .brand span { display: block; font-size: 11px; color: var(--muted); font-weight: 400; }
  .top-links { display: flex; gap: 10px; }
  .top-links a {
    color: var(--muted); text-decoration: none; font-size: 13px;
    padding: 7px 12px; border-radius: 6px; transition: color 0.2s, background 0.2s;
  }
  .top-links a:hover { color: var(--text); background: var(--panel); }
  .hero { max-width: 1080px; margin: 0 auto 40px; padding-top: 48px; }
  .status {
    display: inline-flex; align-items: center; gap: 8px;
    border: 1px solid var(--line); border-radius: 999px;
    padding: 6px 14px; font-size: 12px; color: var(--accent-2);
    background: rgba(53, 214, 176, 0.06); margin-bottom: 22px;
  }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-2); animation: pulse 2s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  h1 {
    font-size: clamp(30px, 5vw, 44px); font-weight: 750; letter-spacing: -0.5px;
    line-height: 1.15; margin-bottom: 14px; max-width: 640px;
  }
  h1 em { font-style: normal; color: var(--accent); }
  .tagline { color: var(--muted); font-size: 17px; margin-bottom: 30px; line-height: 1.65; max-width: 560px; }
  .cta { display: flex; gap: 12px; flex-wrap: wrap; }
  .cta a {
    text-decoration: none; font-size: 14px; font-weight: 600;
    padding: 11px 22px; border-radius: 8px; transition: transform 0.15s, opacity 0.2s;
  }
  .cta a:hover { transform: translateY(-1px); }
  .cta .primary { background: var(--accent); color: #06101f; }
  .cta .ghost { color: var(--text); border: 1px solid var(--line); }
  .section { max-width: 1080px; margin: 0 auto 36px; }
  .section h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px; color: var(--muted); margin-bottom: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
  .card {
    background: linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%);
    border: 1px solid var(--line); border-radius: 8px; padding: 18px;
    transition: border-color 0.2s;
  }
  .card:hover { border-color: #2e4270; }
  .card .num { font-family: var(--mono); font-size: 11px; color: var(--accent); margin-bottom: 10px; }
  .card h3 { font-size: 15px; margin-bottom: 8px; font-weight: 650; }
  .card p { font-size: 13px; color: var(--muted); line-height: 1.55; }
  .endpoint {
    max-width: 1080px; margin: 0 auto 36px;
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px;
    padding: 20px; font-family: var(--mono); font-size: 13px; line-height: 2;
  }
  .endpoint .method { color: var(--accent-2); font-weight: 700; }
  .endpoint .path { color: var(--text); }
  .endpoint .desc { color: var(--muted); font-family: "Segoe UI", sans-serif; font-size: 13px; }
  .endpoint .row { padding: 4px 0; border-bottom: 1px solid var(--line); }
  .endpoint .row:last-child { border-bottom: none; }
  footer {
    max-width: 1080px; margin: 0 auto; padding-top: 20px;
    border-top: 1px solid var(--line); font-size: 12px; color: var(--muted);
    display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  }
  @media (max-width: 640px) {
    .top-links { display: none; }
    .hero { padding-top: 20px; }
  }
</style>
</head>
<body>
<header class="top">
  <div class="brand">
    <div class="logo">A</div>
    <div><b>AgentKiln Memory</b><span>Evidence-only retrieval</span></div>
  </div>
  <nav class="top-links">
    <a href="/docs">Docs</a>
    <a href="/openapi.json">OpenAPI</a>
    <a href="/health">Health</a>
  </nav>
</header>
<section class="hero">
  <div class="status"><span class="pulse"></span> Service online · v1.0.0</div>
  <h1>Long-term memory that returns <em>evidence</em>, not answers.</h1>
  <p class="tagline">Agent conversations are stored under strict user isolation, indexed with hybrid lexical and vector retrieval, and returned as verbatim source windows. Auditable, testable, and ready for evaluation.</p>
  <div class="cta">
    <a class="primary" href="/docs">Explore the API</a>
    <a class="ghost" href="/health">Check health</a>
  </div>
</section>
<section class="section">
  <h2>How it works</h2>
  <div class="grid">
    <div class="card"><div class="num">01</div><h3>Hybrid retrieval</h3><p>FTS5 lexical search and vector similarity, fused by reciprocal rank. Exact terms and semantic matches both surface.</p></div>
    <div class="card"><div class="num">02</div><h3>Session windows</h3><p>Matched evidence expands to adjacent turns in the same conversation, restoring context a single message loses.</p></div>
    <div class="card"><div class="num">03</div><h3>Strict isolation</h3><p>Every memory, index entry, and vector is scoped to the exact user_id. Cross-user access returns empty.</p></div>
    <div class="card"><div class="num">04</div><h3>Idempotent writes</h3><p>Safe retries with payload conflict detection. The same request_id never duplicates or overwrites.</p></div>
  </div>
</section>
<section class="section">
  <h2>Endpoints</h2>
  <div class="endpoint">
    <div class="row"><span class="method">POST</span> <span class="path">/add</span> <span class="desc">Store messages with idempotency</span></div>
    <div class="row"><span class="method">POST</span> <span class="path">/search</span> <span class="desc">Retrieve ranked evidence</span></div>
    <div class="row"><span class="method">GET</span> <span class="path">/health</span> <span class="desc">Service health and model readiness</span></div>
  </div>
</section>
<footer>
  <span>AgentKiln Memory · textual retrieval Track · Open Retrieval Benchmark</span>
  <span>Python 3.10+ · FastAPI · PostgreSQL</span>
</footer>
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

app = create_app()
app.docs_url = None
app.redoc_url = None


@app.get('/', include_in_schema=False)
def root():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(ROOT_PAGE)


@app.get('/docs', include_in_schema=False)
def custom_docs():
    return get_swagger_ui_html(openapi_url=app.openapi_url, title=app.title + ' API')
