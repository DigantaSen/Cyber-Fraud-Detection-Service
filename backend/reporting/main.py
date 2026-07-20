"""
Platform Service Template — FastAPI
"""
import sys
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

from config import settings

logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {extra[service]} | {extra[trace_id]} | {message}",
    serialize=True,
    level="INFO",
)
logger = logger.bind(service=settings.SERVICE_NAME, trace_id="—")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.SERVICE_NAME} starting up")
    yield
    logger.info(f"{settings.SERVICE_NAME} shutting down")

app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
).instrument(app).expose(app, endpoint="/metrics")

@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    otel_trace_id = "—"
    req_logger = logger.bind(
        trace_id=otel_trace_id,
        correlation_id=correlation_id,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    req_logger.info(
        "request_completed",
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-ID"] = request_id
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "requestId": request_id,
            "correlationId": correlation_id,
            "errorCode": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "details": None,
        },
    )

@app.get("/health/live", tags=["Health"])
async def liveness():
    return {"status": "alive", "service": settings.SERVICE_NAME}

@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request):
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "service": settings.SERVICE_NAME},
    )

from routers import reports
app.include_router(reports.router, tags=["Reporting"])
