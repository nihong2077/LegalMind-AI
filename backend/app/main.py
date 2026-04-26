import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from .core.config import settings
from .core.llm_client import close_llm_client, get_llm_client
from .core.redis_client import close_redis, init_redis, redis_health_check
from .core.database import init_db, close_db
from .core.qdrant_client import get_qdrant_client, close_qdrant_client
from .routers import gateway, auth, cases, agents, voice, evaluation
from .models import User, Case, Memory

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
    # 初始化服务
    try:
        await init_redis()
    except Exception as e:
        print(f"Redis初始化失败: {e}")
    
    try:
        await init_db()
    except Exception as e:
        print(f"数据库初始化失败: {e}")
    
    try:
        get_llm_client()
    except Exception as e:
        print(f"LLM客户端初始化失败: {e}")
    
    try:
        qdrant_client = get_qdrant_client()
        # 初始化默认集合
        await qdrant_client.create_collection("legal_knowledge")
    except Exception as e:
        print(f"Qdrant初始化失败: {e}")
    
    yield
    
    # 关闭服务
    try:
        await close_llm_client()
    except Exception as e:
        print(f"关闭LLM客户端失败: {e}")
    
    try:
        await close_redis()
    except Exception as e:
        print(f"关闭Redis失败: {e}")
    
    try:
        await close_db()
    except Exception as e:
        print(f"关闭数据库失败: {e}")
    
    try:
        await close_qdrant_client()
    except Exception as e:
        print(f"关闭Qdrant失败: {e}")


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


# 包含路由
app.include_router(gateway.router)
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(cases.router, prefix=settings.API_PREFIX)
app.include_router(agents.router, prefix=settings.API_PREFIX)
app.include_router(voice.router, prefix=settings.API_PREFIX)
app.include_router(evaluation.router, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    return {"message": f"{settings.PROJECT_NAME} API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    redis_status = await redis_health_check()
    llm_status = await get_llm_client().health_check()
    qdrant_status = {"status": "healthy" if await get_qdrant_client().health_check() else "unhealthy"}
    
    overall = "healthy"
    if (redis_status["status"] != "healthy" or 
        llm_status["status"] != "healthy" or 
        qdrant_status["status"] != "healthy"):
        unhealthy = (redis_status["status"] == "unhealthy" or 
                    llm_status["status"] == "unhealthy" or 
                    qdrant_status["status"] == "unhealthy")
        overall = "unhealthy" if unhealthy else "degraded"
    
    return {
        "status": overall,
        "version": "1.0.0",
        "redis": redis_status,
        "litellm": llm_status,
        "qdrant": qdrant_status,
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

