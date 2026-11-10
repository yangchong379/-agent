import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.api.conversations import router as conversations_router
from app.config import get_settings
from app.core.logging import bind_request_id, configure_logging, request_id_var
from app.db.base import init_db
from app.web.routes import router as web_router


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="3.3.0",
    description="多租户、可审计、人工审批的企业级求职与面试 Agent。",
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_api_key.get_secret_value(),
    session_cookie="career_agent_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=settings.app_env.lower() == "production",
)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))[:64]
    token = bind_request_id(request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/ui"):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self'; img-src 'self' data:; "
                "form-action 'self'; frame-ancestors 'none'"
            )
        return response
    finally:
        request_id_var.reset(token)


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    logger.exception("unhandled request error")
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error", "request_id": request_id_var.get()},
    )


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui", status_code=303)


app.include_router(web_router)
app.include_router(router)
app.include_router(conversations_router)
