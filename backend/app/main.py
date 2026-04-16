import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from .core.config import settings
from .core.llm_client import close_llm_client, get_llm_client
from .core.redis_client import close_redis, init_redis, redis_health_check
from .routers import gateway

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)
CIRCUIT_BREAKER_TRIPS = Counter(
    "circuit_breaker_trips_total",
    "Circuit breaker trip count",
    ["name"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    get_llm_client()
    yield
    await close_llm_client()
    await close_redis()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    method = request.method
    endpoint = request.url.path

    with REQUEST_LATENCY.labels(method=method, endpoint=endpoint).time():
        response = await call_next(request)

    REQUEST_COUNT.labels(
        method=method,
        endpoint=endpoint,
        status=response.status_code,
    ).inc()
    return response


EXCEPTION_STATUS_MAP = {
    PermissionError: status.HTTP_403_FORBIDDEN,
    FileNotFoundError: status.HTTP_404_NOT_FOUND,
    TimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
    ConnectionError: status.HTTP_502_BAD_GATEWAY,
    RuntimeError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ValueError: status.HTTP_400_BAD_REQUEST,
    KeyError: status.HTTP_400_BAD_REQUEST,
    TypeError: status.HTTP_400_BAD_REQUEST,
}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    for exc_type, http_status in EXCEPTION_STATUS_MAP.items():
        if isinstance(exc, exc_type):
            traceback.print_exc()
            return JSONResponse(
                status_code=http_status,
                content={
                    "detail": str(exc),
                    "type": exc_type.__name__,
                },
            )

    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "服务器内部错误",
            "type": type(exc).__name__,
        },
    )


app.include_router(gateway.router)


@app.get("/")
async def root():
    return {"message": f"{settings.PROJECT_NAME} API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    redis_status = await redis_health_check()
    llm_status = await get_llm_client().health_check()
    overall = "healthy"
    if redis_status["status"] != "healthy" or llm_status["status"] != "healthy":
        overall = "degraded" if redis_status["status"] != "unhealthy" and llm_status["status"] != "unhealthy" else "unhealthy"
    return {
        "status": overall,
        "version": "1.0.0",
        "redis": redis_status,
        "litellm": llm_status,
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
