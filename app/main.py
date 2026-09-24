from __future__ import annotations

import hmac
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError

from . import __version__
from .config import Settings
from .llm import LLMUnavailable
from .logging_setup import configure_uvicorn_timestamps
from .schemas import AddRequest, AddResponse, HealthResponse, SearchRequest, SearchResponse
from .service import MemoryService


validation_logger = logging.getLogger("uvicorn.error")
SAFE_VALIDATION_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
SENSITIVE_FIELD_NAME = re.compile(r"secret|token|key|password|credential|authorization", re.I)


def _validation_field(value: object) -> str:
    if isinstance(value, int):
        return f"[{value}]" if 0 <= value < 10_000 else "[index]"
    if isinstance(value, str) and SAFE_VALIDATION_FIELD.fullmatch(value):
        if not SENSITIVE_FIELD_NAME.search(value):
            return value
    return "<redacted>"


def _validation_error_labels(exc: RequestValidationError) -> str:
    errors = exc.errors()
    labels = []
    for error in errors[:12]:
        location = error.get("loc") or ()
        field = ".".join(_validation_field(part) for part in location)
        kind = error.get("type", "unknown")
        if not isinstance(kind, str) or not SAFE_VALIDATION_FIELD.fullmatch(kind):
            kind = "unknown"
        labels.append(f"{field or 'unknown'}:{kind}")
    if len(errors) > 12:
        labels.append(f"{len(errors) - 12}_more")
    return ",".join(labels)


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
    color-scheme: light;
    --bg: #f4f2eb;
    --paper: #fffefa;
    --ink: #1b332a;
    --muted: #5e7167;
    --line: #d9e0d6;
    --forest: #235f4d;
    --forest-deep: #173d34;
    --sage: #dce9dc;
    --clay: #aa5639;
    --clay-light: #f6e8db;
    --mono: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0;
    color: var(--ink);
    background: radial-gradient(circle at 84% 2%, #e2ecdf 0, transparent 30%), var(--bg);
    font-family: "Segoe UI", system-ui, sans-serif;
    min-width: 320px;
  }
  a { color: inherit; }
  a:focus-visible { outline: 3px solid var(--clay); outline-offset: 4px; }
  .wrap { max-width: 1180px; margin: auto; padding: 0 30px; }
  .top {
    display: flex; align-items: center; justify-content: space-between; gap: 24px;
    padding: 24px 0; border-bottom: 1px solid var(--line);
  }
  .brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .brand-mark {
    display: grid; place-items: center; width: 42px; height: 42px; flex: 0 0 auto;
    border-radius: 12px; background: var(--forest-deep); color: #e6b78b;
    box-shadow: 0 7px 18px #173d3422;
  }
  .brand-mark svg { width: 27px; height: 27px; }
  .brand b { display: block; font-size: 17px; letter-spacing: -.025em; }
  .brand small { display: block; font-size: 11px; color: var(--muted); margin-top: 2px; }
  .links { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
  .links a { font-size: 13px; font-weight: 650; text-decoration: none; padding: 9px 12px; border-radius: 8px; }
  .links a:hover { background: #e7ede5; color: var(--forest); }
  .links .nav-cta { background: var(--forest-deep); color: white; margin-left: 8px; padding: 10px 16px; }
  .links .nav-cta:hover { background: var(--forest); color: white; }
  .hero { display: grid; grid-template-columns: 1.05fr .95fr; align-items: center; gap: 6%; padding: 86px 0 76px; }
  .eyebrow { display: inline-flex; align-items: center; gap: 9px; color: var(--forest); font: 700 11px var(--mono); letter-spacing: .11em; text-transform: uppercase; }
  .eyebrow::before { content: ""; width: 20px; height: 2px; background: var(--clay); }
  h1 { max-width: 620px; font: 600 clamp(46px, 5.6vw, 72px)/1.04 Georgia, "Times New Roman", serif; letter-spacing: -.055em; margin: 24px 0; }
  h1 em { color: var(--forest); font-style: italic; }
  .tagline { max-width: 520px; color: var(--muted); font-size: 17px; line-height: 1.75; margin: 0 0 30px; }
  .cta { display: flex; flex-wrap: wrap; gap: 12px; }
  .btn { display: inline-flex; align-items: center; justify-content: center; min-height: 46px; padding: 0 22px; border: 1px solid transparent; border-radius: 9px; text-decoration: none; font-size: 14px; font-weight: 700; transition: background .2s, transform .2s, box-shadow .2s; }
  .btn:hover { transform: translateY(-2px); }
  .btn.primary { background: var(--forest-deep); color: white; box-shadow: 0 10px 24px #173d3426; }
  .btn.primary:hover { background: var(--forest); box-shadow: 0 14px 26px #173d3436; }
  .btn.ghost { background: var(--paper); border-color: var(--line); color: var(--forest-deep); }
  .btn.ghost:hover { background: #e9eee8; }
  .assurance { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-top: 32px; color: var(--muted); font-size: 12px; }
  .assurance span::before { content: "✓"; color: var(--forest); font-weight: 800; margin-right: 6px; }
  .preview { position: relative; padding: 18px; border: 1px solid #b7cabc; border-radius: 24px; background: #e6ede3; box-shadow: 0 24px 70px #1b332a1b; transform: rotate(1deg); }
  .preview::before { content: ""; position: absolute; inset: 20px -15px -15px 20px; border: 1px solid #c9d5c7; border-radius: 24px; background: #dce8dc; z-index: -1; transform: rotate(3deg); }
  .preview-inner { overflow: hidden; border-radius: 15px; background: var(--paper); }
  .preview-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--forest-deep); color: #f0f5ee; font: 12px var(--mono); }
  .preview-head .dots { display: flex; gap: 5px; }
  .preview-head i { display: block; width: 6px; height: 6px; border-radius: 50%; background: #c2d5c4; opacity: .7; }
  .preview-body { padding: 20px; }
  .preview-label { display: block; color: var(--muted); font: 700 10px var(--mono); letter-spacing: .12em; text-transform: uppercase; margin-bottom: 8px; }
  .query { padding: 15px 16px; border: 1px solid var(--line); border-radius: 10px; background: #f7f8f4; font-size: 14px; line-height: 1.5; }
  .preview-route { display: flex; align-items: center; gap: 10px; color: var(--forest); font: 700 11px var(--mono); margin: 17px 0; }
  .preview-route::before { content: ""; height: 1px; flex: 1; background: var(--line); }
  .preview-route::after { content: ""; height: 1px; flex: 1; background: var(--line); }
  .evidence { padding: 18px; border: 1px solid #bad1bd; border-left: 4px solid var(--forest); border-radius: 10px; background: #f0f7ef; }
  .evidence p { margin: 10px 0 14px; font: 18px/1.45 Georgia, "Times New Roman", serif; }
  .evidence footer { color: var(--muted); font: 11px var(--mono); }
  .preview-note { color: var(--muted); font-size: 11px; margin: 13px 0 0; text-align: right; }
  .process { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 0 0 82px; }
  .process-step { display: flex; align-items: center; gap: 12px; padding: 16px 18px; border: 1px solid var(--line); border-radius: 12px; background: #fffefaac; font-size: 13px; font-weight: 700; }
  .process-step span { color: var(--clay); font: 700 11px var(--mono); }
  .section { margin-bottom: 78px; }
  .section-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
  .section-kicker { display: block; color: var(--clay); font: 700 11px var(--mono); letter-spacing: .12em; text-transform: uppercase; margin-bottom: 9px; }
  h2 { font: 600 clamp(30px, 3.3vw, 40px)/1.15 Georgia, "Times New Roman", serif; letter-spacing: -.035em; margin: 0; }
  .section-intro { color: var(--muted); max-width: 430px; font-size: 14px; line-height: 1.65; margin: 0; }
  .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
  .card { min-height: 225px; padding: 24px; border: 1px solid var(--line); border-radius: 14px; background: var(--paper); box-shadow: 0 10px 30px #1b332a08; transition: transform .2s, box-shadow .2s; }
  .card:hover { transform: translateY(-4px); box-shadow: 0 16px 35px #1b332a15; }
  .card .num { display: inline-grid; place-items: center; width: 35px; height: 35px; border-radius: 9px; background: var(--clay-light); color: var(--clay); font: 700 12px var(--mono); margin-bottom: 24px; }
  .card h3 { font-size: 16px; margin: 0 0 9px; }
  .card p { color: var(--muted); font-size: 13px; line-height: 1.65; margin: 0; }
  .api-section { padding: 34px; border-radius: 18px; background: var(--forest-deep); color: #f7faf5; }
  .api-section .section-kicker { color: #e6b78b; }
  .api-section .section-intro { color: #c6d7ce; }
  .endpoints { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 24px; }
  .ep-row { padding: 16px; border: 1px solid #598071; border-radius: 10px; background: #ffffff0a; }
  .ep-method { display: inline-block; color: #f2c99d; font: 700 11px var(--mono); margin-right: 9px; }
  .ep-method.get { color: #b5dec3; }
  .ep-path { font: 700 14px var(--mono); }
  .ep-desc { display: block; color: #c6d7ce; font-size: 12px; line-height: 1.5; margin-top: 10px; }
  .site-footer { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; border-top: 1px solid var(--line); padding: 25px 0 35px; color: var(--muted); font-size: 12px; }
  .site-footer a { text-decoration: none; }
  .site-footer a:hover { color: var(--forest); text-decoration: underline; }
  @media (max-width: 950px) {
    .hero { grid-template-columns: 1fr; gap: 46px; padding: 65px 0; }
    .hero-copy { max-width: 680px; }
    .preview { max-width: 620px; transform: none; }
    .grid { grid-template-columns: repeat(2, 1fr); }
    .endpoints { grid-template-columns: 1fr; }
  }
  @media (max-width: 640px) {
    .wrap { padding: 0 18px; }
    .top { align-items: flex-start; flex-direction: column; gap: 14px; padding: 18px 0; }
    .links { width: 100%; justify-content: space-between; }
    .links a { padding: 8px 6px; font-size: 12px; }
    .links .nav-cta { margin-left: 0; padding: 8px 10px; }
    .hero { padding: 54px 0 62px; }
    h1 { font-size: clamp(42px, 12vw, 58px); }
    .tagline { font-size: 15px; }
    .preview { padding: 10px; }
    .preview::before { display: none; }
    .process { grid-template-columns: repeat(2, 1fr); margin-bottom: 64px; }
    .section { margin-bottom: 62px; }
    .section-heading { display: block; }
    .section-intro { margin-top: 14px; }
    .grid { grid-template-columns: 1fr; }
    .card { min-height: 0; }
    .api-section { padding: 25px 18px; }
  }
  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    .btn, .card { transition: none; }
  }
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div class="brand">
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M6 23V9l10 8 10-8v14" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="6" cy="9" r="2" fill="currentColor"/><circle cx="16" cy="17" r="2" fill="currentColor"/><circle cx="26" cy="9" r="2" fill="currentColor"/>
      </svg>
    </span>
    <div><b>AgentKiln Memory</b><small>Evidence-first agent memory</small></div>
  </div>
  <nav class="links" aria-label="Main navigation">
    <a href="#how">How it works</a>
    <a href="#api">Endpoints</a>
    <a class="nav-cta" href="/docs">API docs ↗</a>
  </nav>
</header>
<section class="hero">
  <div class="hero-copy">
    <span class="eyebrow">Memory infrastructure for agents</span>
    <h1>The answer starts with <em>evidence.</em></h1>
    <p class="tagline">Keep conversation history searchable and give agents the exact source behind a memory. AgentKiln Memory combines lexical and vector retrieval, then returns ranked conversation windows for the caller.</p>
    <div class="cta">
      <a class="btn primary" href="/docs">Explore the API →</a>
      <a class="btn ghost" href="#how">See how it works</a>
    </div>
    <div class="assurance" aria-label="Service properties">
      <span>Isolated by user</span><span>Searchable after Add</span><span>Source windows</span>
    </div>
  </div>
  <div class="preview" aria-label="Illustrative search result">
    <div class="preview-inner">
      <div class="preview-head"><span>MEMORY / SEARCH</span><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span></div>
      <div class="preview-body">
        <span class="preview-label">Question</span>
        <div class="query">What tea did I choose last time?</div>
        <div class="preview-route">ranked source</div>
        <div class="evidence">
          <span class="preview-label">Conversation evidence</span>
          <p>I chose jasmine tea again.</p>
          <footer>session / message / source window</footer>
        </div>
        <p class="preview-note">Illustrative result · your data stays scoped to its user</p>
      </div>
    </div>
  </div>
</section>
<div class="process" aria-label="Memory workflow">
  <div class="process-step"><span>01</span> Add conversations</div>
  <div class="process-step"><span>02</span> Index memories</div>
  <div class="process-step"><span>03</span> Search context</div>
  <div class="process-step"><span>04</span> Return evidence</div>
</div>
<section class="section" id="how">
  <div class="section-heading">
    <div><span class="section-kicker">Built for reliable retrieval</span><h2>From conversation to context.</h2></div>
    <p class="section-intro">The service stores messages, finds relevant passages, and returns the surrounding turns an agent needs to judge them.</p>
  </div>
  <div class="grid">
    <div class="card"><div class="num">01</div><h3>Hybrid retrieval</h3><p>Lexical and vector candidates bring exact terms and semantic matches into one ranked result set.</p></div>
    <div class="card"><div class="num">02</div><h3>Session windows</h3><p>Matched evidence expands to adjacent turns in the same conversation, restoring context a single message loses.</p></div>
    <div class="card"><div class="num">03</div><h3>Temporal ranking</h3><p>Time-aware scoring detects latest and earliest intent, with correction-aware suppression of superseded memories.</p></div>
    <div class="card"><div class="num">04</div><h3>Strict isolation</h3><p>Memories and retrieval are scoped to the exact user ID so evidence stays with its owner.</p></div>
  </div>
</section>
<section class="section api-section" id="api">
  <div class="section-heading">
    <div><span class="section-kicker">Simple interface</span><h2>Three endpoints. Clear purpose.</h2></div>
    <p class="section-intro">Add messages synchronously, search for ranked evidence, and check service readiness.</p>
  </div>
  <div class="endpoints">
    <div class="ep-row"><span class="ep-method">POST</span><span class="ep-path">/add</span><span class="ep-desc">Store messages with idempotency and conflict detection.</span></div>
    <div class="ep-row"><span class="ep-method">POST</span><span class="ep-path">/search</span><span class="ep-desc">Retrieve ranked evidence without generating answers.</span></div>
    <div class="ep-row"><span class="ep-method get">GET</span><span class="ep-path">/health</span><span class="ep-desc">Inspect service health and model readiness.</span></div>
  </div>
</section>
<footer class="site-footer">
  <span>AgentKiln Memory · Evidence-first memory for AI agents</span>
  <span><a href="/docs">Docs</a> · <a href="/openapi.json">OpenAPI</a> · <a href="/health">Health</a></span>
</footer>
</div>
</body>
</html>"""
def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    service = MemoryService(resolved)
    try:
        service.initialize()
    except Exception:
        service.close()
        raise

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="AgentKiln Memory", version=__version__, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def log_request_validation(request: Request, exc: RequestValidationError):
        if request.url.path in {"/add", "/search", "/v1/memory/add", "/v1/memory/search"}:
            client = request.client
            address = f"{client.host}:{client.port}" if client else "unknown"
            validation_logger.warning(
                "request validation failed client=%s method=%s path=%s status=422 fields=%s",
                address,
                request.method,
                request.url.path,
                _validation_error_labels(exc),
            )
        return await request_validation_exception_handler(request, exc)

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
