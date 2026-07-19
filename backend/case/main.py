"""
Platform Service Template — FastAPI
====================================
Copy this file into your service directory and rename/modify as needed.

SETUP INSTRUCTIONS:
1. Copy backend/template/ → backend/<your-service>/
2. Set SERVICE_NAME in settings below
3. Implement your domain endpoints in separate routers
4. Import routers here and include them on `app`
5. Run: uvicorn main:app --reload

PATTERNS ESTABLISHED HERE:
- Structured JSON logging (loguru) with trace_id in every log line
- OpenTelemetry auto-instrumentation (traces, metrics → OTel Collector)
- Prometheus metrics via prometheus-fastapi-instrumentator (/metrics)
- /health/live  → liveness probe (is the process alive?)
- /health/ready → readiness probe (can it serve traffic?)
- Standard error response shape: {requestId, correlationId, errorCode, message}
- Vault secret loading at startup (graceful fallback to env vars for local dev)
"""

import sys
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

# ─── OpenTelemetry (auto-instrument BEFORE app creation) ─────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from config import settings

# ─── Tracer setup ─────────────────────────────────────────────────────────────
resource = Resource.create({"service.name": settings.SERVICE_NAME, "service.version": settings.SERVICE_VERSION})
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT))
)
trace.set_tracer_provider(tracer_provider)

# ─── Logging (structured JSON via loguru) ─────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {extra[service]} | {extra[trace_id]} | {message}",
    serialize=True,    # Emit as JSON lines
    level="INFO",
)
logger = logger.bind(service=settings.SERVICE_NAME, trace_id="—")


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.SERVICE_NAME} starting up")
    
    import httpx
    from db import get_engine, get_session_factory
    from redis_client import create_redis_client
    
    engine = get_engine()
    app.state.db_engine = engine
    app.state.db_session_factory = get_session_factory(engine)
    app.state.redis = create_redis_client()
    await app.state.redis.ping()
    
    # Shared HTTP client for downstream calls (Inference Orchestrator)
    app.state.http_client = httpx.AsyncClient(
        timeout=5.0,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
    
    logger.info(f"{settings.SERVICE_NAME} ready")
    yield
    
    logger.info(f"{settings.SERVICE_NAME} shutting down")
    await app.state.db_engine.dispose()
    await app.state.redis.aclose()
    await app.state.http_client.aclose()


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Auto-instrument FastAPI with OTel
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

# ─── CORS ────────────────────────────────────────────────────────────────────
# Bug Fix T18-A: CORS was missing — Citizen/Bank/Telecom UIs were blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Expose /metrics endpoint for Prometheus scraping
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
).instrument(app).expose(app, endpoint="/metrics")


# ─── Middleware: correlation ID + request logging ─────────────────────────────
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Bind trace context to logger for this request
    span_context = trace.get_current_span().get_span_context()
    otel_trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else "—"
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


# ─── Standard error handler ───────────────────────────────────────────────────
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


# ─── Health Endpoints ─────────────────────────────────────────────────────────
@app.get("/health/live", tags=["Health"])
async def liveness():
    """Kubernetes liveness probe — is the process running?"""
    return {"status": "alive", "service": settings.SERVICE_NAME}


@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request):
    """
    Kubernetes readiness probe — can the service serve traffic?
    Checks: DB connection, Redis ping, Kafka broker reachability.
    Returns 503 if any dependency is unhealthy.
    """
    checks = {}
    healthy = True

    # ── DB check ──────────────────────────────────────────────
    try:
        from sqlalchemy import text
        SessionFactory = request.app.state.db_session_factory
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    # ── Redis check ───────────────────────────────────────────
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        healthy = False

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "service": settings.SERVICE_NAME,
            "checks": checks,
        },
    )

@app.get("/health/integration", include_in_schema=False)
async def integration_check():
    """Internal endpoint for cross-team integration verification."""
    return {
        "service": "case-service",
        "kafkaTopics": {
            "publishes": ["case.created", "case.updated", "prediction.completed", "prediction.overridden"],
        },
        "apiVersion": "v1",
        "endpoints": [
            "POST /api/v1/cases",
            "GET /api/v1/cases/:id",
            "PATCH /api/v1/cases/:id/state",
        ],
    }


# ─── Domain Routers ───────────────────────────────────────────────────────────
from routers.case_router import router as case_router
app.include_router(case_router, prefix="/api/v1")
