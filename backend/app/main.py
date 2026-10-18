import asyncio
import gc
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

from .core.config import settings
from .core.health import readiness_report
from .core.llm_client import close_llm_client, get_llm_client
from .core.logging import RequestContextMiddleware, setup_logging
from .core.metrics import PrometheusASGIMiddleware
from .core.pg_client import close_pg, init_pg
from .core.qdrant_client import close_qdrant, init_qdrant
from .core.redis_client import close_redis, init_redis, redis_health_check
from .core.response import LegacyEnvelopeMiddleware, register_exception_handlers
from .core.tracing import instrument_app, setup_tracing
from .routers import agents, collab, conversations, gateway, memory

# 尽早统一日志格式（structlog JSON + stdlib 桥接）
setup_logging()
# OTel 常开：全局 instrumentor + W3C 传播（FastAPI app 在路由注册后 instrument）
setup_tracing()

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis: 必须成功，带重试
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            await init_redis()
            logger.info("Redis 初始化成功")
            break
        except Exception as e:
            last_exc = e
            logger.warning("Redis 初始化失败 (第%d次): %s", attempt + 1, e)
            await asyncio.sleep(2 ** attempt)
    else:
        logger.critical("Redis 初始化失败，服务无法启动")
        raise last_exc  # type: ignore[misc]

    # 初始化默认管理员账号（admin/admin），保证首次部署可登录
    try:
        from .core.user_service import ensure_default_admin
        await ensure_default_admin()
        logger.info("默认管理员账号已就绪")
    except Exception as e:
        logger.warning("默认管理员账号初始化失败: %s", e)

    # PostgreSQL: 必须成功，带重试
    pg_last_exc: Exception | None = None
    for attempt in range(5):
        try:
            await init_pg()
            logger.info("PostgreSQL 初始化成功")
            break
        except Exception as e:
            pg_last_exc = e
            logger.warning("PG 初始化失败 (第%d次): %s", attempt + 1, e)
            await asyncio.sleep(2 ** attempt)
    else:
        logger.critical("PostgreSQL 初始化失败，服务无法启动")
        raise pg_last_exc  # type: ignore[misc]

    # LangGraph Checkpointer：连 legalmind_app 建 checkpoint 三表；可降级
    try:
        from .core.checkpoint import init_checkpointer
        await init_checkpointer()
    except Exception as e:
        logger.warning("LangGraph 检查点初始化失败（协同中断/恢复暂不可用）: %s", e)

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

    # Kafka：懒连，启动期不建连；此处只记录开关状态
    logger.info(
        "Kafka 事件总线：%s（bootstrap=%s）",
        "ENABLED，首次发送时懒连" if settings.ENABLE_KAFKA else "DISABLED，事件走进程内降级",
        settings.KAFKA_BOOTSTRAP_SERVERS,
    )

    yield

    monitor_task.cancel()
    from .core.events import event_bus
    await event_bus.close()
    from .core.checkpoint import close_checkpointer
    await close_checkpointer()
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
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理：新路由（EnvelopeRouter/raise BizException）走统一信封；
# 旧路由保持 FastAPI 默认错误形状，再由 LegacyEnvelopeMiddleware 统一穿信封
# （T0.12；旧 global_exception_handler 的异常→状态映射已迁入 response.py）。
register_exception_handlers(app)


app.include_router(gateway.router)
app.include_router(conversations.router)
app.include_router(collab.router)
app.include_router(agents.router)
app.include_router(memory.router)


@app.get("/")
async def root():
    return {"message": f"{settings.PROJECT_NAME} API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    redis_status = await redis_health_check()
    llm_status = await get_llm_client().health_check()

    pg_statuses = {}
    try:
        from .core.pg_client import ENGINES, app_engine
        engines = {**ENGINES, "app": app_engine}
        for name, engine in engines.items():
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


@app.get("/healthz")
async def healthz():
    """存活探针：进程在即 200，**不查任何依赖**（断 Redis 仍返回 200）。"""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """就绪探针：Redis/PG/Qdrant 健康、Kafka 生产者已连（或开关关闭）才 200。"""
    report = await readiness_report()
    http_status = 200 if report["ready"] else 503
    return JSONResponse(content=report, status_code=http_status)


# X-Request-ID 全链路 + 结构化访问日志：必须包裹在「最外层」。
# Starlette 的 ServerErrorMiddleware 恒为 app 内建栈最外层，处理未捕获异常时
# 经其外层传入的 send 发出 500 响应后再 re-raise；只有处在它外面，request-id
# 中间件才能给 500 响应补 X-Request-ID 头、读到真实状态码，并保证异常处理器
# 执行期间 contextvar 仍绑定（信封 request_id 不漂移）。
#
# 顺序：instrument_app 重写 FastAPI 内建栈（实测 otel-fastapi 0.66b1：
# OTel 中间件位于内建栈的 ServerError 外侧），再逐层包裹 —— 请求链为
# Client → RequestContext → Prometheus → Envelope → OTel → ServerError → 路由。
# Envelope 必须在 ServerError 外侧：未捕获异常被内建栈转成 500 后，
# 仍由 Envelope 补成统一错误信封（request_id 与 X-Request-ID 同源）。
instrument_app(app)
app = LegacyEnvelopeMiddleware(app)
app = PrometheusASGIMiddleware(app)
app = RequestContextMiddleware(app)
