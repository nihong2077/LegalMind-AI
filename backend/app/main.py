import asyncio
import gc
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

from .core.config import settings
from .core.llm_client import close_llm_client, get_llm_client
from .core.pg_client import close_pg, init_pg
from .core.qdrant_client import close_qdrant, init_qdrant
from .core.redis_client import close_redis, init_redis, redis_health_check
from .routers import gateway

logger = logging.getLogger(__name__)

# ========== 内存监控与回收 ==========
MEMORY_WARNING_THRESHOLD = 0.80   # 可用内存低于 20% 时告警
MEMORY_CRITICAL_THRESHOLD = 0.90  # 可用内存低于 10% 时强制回收
MEMORY_CHECK_INTERVAL = 30        # 每 30 秒检查一次


def _get_memory_info() -> dict:
    """读取 /proc/meminfo 获取内存状态"""
    info = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    value = int(parts[1])  # kB
                    info[key] = value
    except Exception:
        pass
    return info


def get_memory_usage() -> dict:
    """获取当前内存使用情况"""
    info = _get_memory_info()
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = total - available
    if total == 0:
        return {"total_gb": 0, "used_gb": 0, "available_gb": 0, "usage_pct": 0}

    return {
        "total_gb": round(total / 1024 / 1024, 2),
        "used_gb": round(used / 1024 / 1024, 2),
        "available_gb": round(available / 1024 / 1024, 2),
        "usage_pct": round(used / total * 100, 1),
    }


async def memory_monitor_task():
    """后台定时任务：监控内存并在高占用时自动回收"""
    while True:
        await asyncio.sleep(MEMORY_CHECK_INTERVAL)
        try:
            info = _get_memory_info()
            total = info.get("MemTotal", 0)
            available = info.get("MemAvailable", 0)
            if total == 0:
                continue

            usage_ratio = (total - available) / total

            if usage_ratio >= MEMORY_CRITICAL_THRESHOLD:
                logger.warning(
                    "内存严重不足！使用率 %.1f%% (可用 %.1f GB / 总计 %.1f GB)，执行强制 GC",
                    usage_ratio * 100,
                    available / 1024 / 1024,
                    total / 1024 / 1024,
                )
                gc.collect()
                # 尝试释放 GPU 缓存
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        logger.info("已释放 GPU 显存缓存")
                except ImportError:
                    pass

            elif usage_ratio >= MEMORY_WARNING_THRESHOLD:
                logger.warning(
                    "内存使用偏高：%.1f%% (可用 %.1f GB / 总计 %.1f GB)",
                    usage_ratio * 100,
                    available / 1024 / 1024,
                    total / 1024 / 1024,
                )
                gc.collect()

        except Exception as e:
            logger.error("内存监控任务异常: %s", e)

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
    # Redis: 必须成功，带重试
    for attempt in range(5):
        try:
            await init_redis()
            logger.info("Redis 初始化成功")
            break
        except Exception as e:
            logger.warning("Redis 初始化失败 (第%d次): %s", attempt + 1, e)
            await asyncio.sleep(2 ** attempt)
    else:
        logger.critical("Redis 初始化失败，服务无法启动")
        raise

    # PostgreSQL: 必须成功，带重试
    for attempt in range(5):
        try:
            await init_pg()
            logger.info("PostgreSQL 初始化成功")
            break
        except Exception as e:
            logger.warning("PG 初始化失败 (第%d次): %s", attempt + 1, e)
            await asyncio.sleep(2 ** attempt)
    else:
        logger.critical("PostgreSQL 初始化失败，服务无法启动")
        raise

    # Qdrant: 可降级
    try:
        await init_qdrant()
        logger.info("Qdrant 初始化成功")
    except Exception as e:
        logger.warning("Qdrant 初始化失败，向量检索不可用: %s", e)

    # LLM: 可降级
    try:
        get_llm_client()
        logger.info("LLM 客户端初始化成功")
    except Exception as e:
        logger.warning("LLM 客户端初始化失败: %s", e)

    # 启动内存监控后台任务
    monitor_task = asyncio.create_task(memory_monitor_task())
    logger.info("内存监控已启动 (告警阈值=%.0f%%, 强制回收阈值=%.0f%%)",
                MEMORY_WARNING_THRESHOLD * 100, MEMORY_CRITICAL_THRESHOLD * 100)

    yield

    monitor_task.cancel()
    await close_llm_client()
    await close_qdrant()
    await close_pg()
    await close_redis()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGINS if hasattr(settings, 'CORS_ORIGINS') else "http://localhost:3000"],
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
    logger.exception("未处理异常 [%s %s]", request.method, request.url.path)
    for exc_type, http_status in EXCEPTION_STATUS_MAP.items():
        if isinstance(exc, exc_type):
            return JSONResponse(
                status_code=http_status,
                content={
                    "detail": str(exc),
                    "type": exc_type.__name__,
                },
            )

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

    pg_statuses = {}
    try:
        from .core.pg_client import ENGINES
        for name, engine in ENGINES.items():
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                pg_statuses[name] = {"status": "healthy"}
            except Exception as e:
                pg_statuses[name] = {"status": "unhealthy", "error": str(e)}
    except Exception as e:
        pg_statuses = {"error": str(e)}

    qdrant_status = {"status": "healthy"}
    try:
        from .core.qdrant_client import COLLECTIONS, get_qdrant_client
        client = get_qdrant_client()
        for name, collection in COLLECTIONS.items():
            try:
                await client.get_collection(collection)
            except Exception as e:
                qdrant_status = {"status": "degraded", "error": f"{collection}: {e}"}
    except Exception as e:
        qdrant_status = {"status": "unhealthy", "error": str(e)}

    components = [redis_status, llm_status, qdrant_status]
    components.extend(pg_statuses.values() if isinstance(pg_statuses, dict) and "error" not in pg_statuses else [pg_statuses])
    unhealthy = any(c.get("status") == "unhealthy" for c in components if isinstance(c, dict))
    degraded = any(c.get("status") != "healthy" for c in components if isinstance(c, dict))

    overall = "healthy"
    if unhealthy:
        overall = "unhealthy"
    elif degraded:
        overall = "degraded"

    return {
        "status": overall,
        "version": "1.0.0",
        "redis": redis_status,
        "litellm": llm_status,
        "postgres": pg_statuses,
        "qdrant": qdrant_status,
        "memory": get_memory_usage(),
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
