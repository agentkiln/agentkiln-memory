from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, status

from . import __version__
from .config import Settings
from .llm import LLMUnavailable
from .schemas import AddRequest, AddResponse, HealthResponse, SearchRequest, SearchResponse
from .service import MemoryService


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


@app.get('/docs', include_in_schema=False)
def custom_docs():
    return get_swagger_ui_html(openapi_url=app.openapi_url, title=app.title + ' API')
