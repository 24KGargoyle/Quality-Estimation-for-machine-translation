import logging
import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from meeting_intel.api.routers import auth, chat, discussions, groups, meetings, messages
from meeting_intel.config import get_settings

settings = get_settings()

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger("meeting_intel")

app = FastAPI(title="Meeting Intelligence Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = int((time.perf_counter() - start) * 1000)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.headers.get("x-request-id", "unknown")
    logger.error("unhandled_exception", request_id=request_id, path=request.url.path, error=str(exc))
    # Never leak stack traces / internals to the client.
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})


app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(chat.router)
app.include_router(groups.router)
app.include_router(messages.router)
app.include_router(messages.feedback_router)
app.include_router(discussions.router)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "graph_configured": settings.graph_configured,
        "llm_configured": settings.llm_configured,
        "auth_provider": settings.auth_provider,
    }
