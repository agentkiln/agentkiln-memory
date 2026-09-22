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
    --bg: #0b1220;
    --panel: #111a2e;
    --line: #223055;
    --text: #e8edf7;
    --muted: #93a1bd;
    --accent: #4f8cff;
    --accent-2: #38d3b3;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Segoe UI", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 20% -10%, #16233f 0%, var(--bg) 60%);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  main { width: 100%; max-width: 720px; }
  .badge {
    display: inline-flex; align-items: center; gap: 8px;
    border: 1px solid var(--line); border-radius: 999px;
    padding: 6px 14px; font-size: 13px; color: var(--muted);
    margin-bottom: 20px;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-2); }
  h1 { font-size: 34px; font-weight: 700; letter-spacing: 0; margin-bottom: 10px; }
  .tagline { color: var(--muted); font-size: 16px; margin-bottom: 28px; line-height: 1.6; }
  .grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 14px; margin-bottom: 28px;
  }
  .card {
    background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
    padding: 16px;
  }
  .card h3 { font-size: 14px; color: var(--accent); margin-bottom: 6px; font-weight: 600; }
  .card p { font-size: 13px; color: var(--muted); line-height: 1.5; }
  .links { display: flex; gap: 12px; flex-wrap: wrap; }
  .links a {
    color: var(--text); text-decoration: none;
    border: 1px solid var(--line); border-radius: 8px;
    padding: 10px 18px; font-size: 14px; transition: border-color 0.2s;
  }
  .links a:hover { border-color: var(--accent); }
  footer { margin-top: 28px; font-size: 12px; color: var(--muted); }
  footer code { background: var(--panel); border-radius: 4px; padding: 2px 6px; }
</style>
</head>
<body>
<main>
  <div class="badge"><span class="dot"></span> Evidence-only memory service · online</div>
  <h1>AgentKiln Memory</h1>
  <p class="tagline">Hybrid lexical and vector retrieval over agent conversations. Returns verbatim source evidence, never generated answers.</p>
  <div class="grid">
    <div class="card"><h3>Hybrid retrieval</h3><p>FTS5 lexical search fused with vector similarity by reciprocal rank.</p></div>
    <div class="card"><h3>Strict isolation</h3><p>Every memory scoped to the exact user_id supplied by the caller.</p></div>
    <div class="card"><h3>Idempotent Add</h3><p>Safe retries with conflict detection on request_id and payload.</p></div>
    <div class="card"><h3>Optional rerank</h3><p>External reranker with automatic fallback to rule-based ranking.</p></div>
  </div>
  <div class="links">
    <a href="/docs">API Docs</a>
    <a href="/openapi.json">OpenAPI Schema</a>
    <a href="/health">Health</a>
  </div>
  <footer>Endpoints: <code>POST /add</code> <code>POST /search</code> <code>GET /health</code></footer>
</main>
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
