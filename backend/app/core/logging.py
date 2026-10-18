"""
结构化日志与 X-Request-ID 全链路中间件（Harness §7.3）

- structlog 输出 JSON 到 stdout（compose 可直接采集）；本地可切 LOG_FORMAT=console。
- 现有代码大量使用标准库 ``logging.getLogger``，这里用 ProcessorFormatter
  把 stdlib 日志桥接进 structlog，使所有日志行统一为 JSON 并自动带上 request_id。
- 中间件：读取/生成 X-Request-ID，写入响应头，绑定到 contextvar；
  尽力从 JWT 解析 user_id（仅用于日志，鉴权失败不影响请求）；输出一行访问日志。

日志字段：request_id, user_id, method, route, status, latency_ms
（retry_count/agent_id/turn_id/case_type 由调用方 bind_contextvars 追加）。
"""
from __future__ import annotations

import logging
import re
import sys
import time
import uuid
from typing import Optional

import jwt
import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings

# 仅放行安全的入站 request id，杜绝日志注入（换行/控制字符/超长）
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{6,64}$")
_REQUEST_ID_HEADER = "x-request-id"

# 复用信封层的 contextvar，保证日志与 ApiResponse.request_id 完全一致
from .response import request_id_ctx  # noqa: E402


def _new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:12]


def _normalize_incoming_id(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    return raw if _REQUEST_ID_RE.match(raw) else None


# ============================================================
# structlog 配置
# ============================================================

def setup_logging() -> None:
    """配置 structlog 并把标准库 root logger 桥接为统一 JSON 输出。

    幂等：重复调用安全（每次重建 handler，避免 uvicorn reload 重复打印）。
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # foreign_pre_chain 也作用于"非 structlog 产生"的 stdlib 日志
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]

    if settings.LOG_FORMAT.lower() == "console":
        renderer: object = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer(
            ensure_ascii=False
        )  # 保留中文，不转 \uXXXX

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # 让 uvicorn 自带的访问日志也走统一格式（不再单独配 handler）
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(noisy)
        lg.handlers = []
        lg.propagate = True

    structlog.get_logger(__name__).debug(
        "logging.initialised", log_format=settings.LOG_FORMAT,
        log_level=settings.LOG_LEVEL,
    )


def get_logger(name: Optional[str] = None):
    """业务代码取 logger 的统一入口（stdlib logger 也会被桥接，二者皆可）。"""
    return structlog.get_logger(name)


# ============================================================
# 纯 ASGI 中间件：request-id 绑定 / 访问日志
# ============================================================

class RequestContextMiddleware:
    """为每个请求绑定 request_id（+user_id），并输出结构化访问日志。

    用纯 ASGI 而非 ``@app.middleware("http")``：能在异常处理器返回响应之后
    仍可靠地补写响应头与耗时（异常已被全局处理器转成正常 Response）。
    """

    def __init__(self, app: ASGIApp):
        self.app = app
        self.log = structlog.get_logger("access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        inbound = _normalize_incoming_id(_header(scope, _REQUEST_ID_HEADER))
        request_id = inbound or _new_request_id()

        # 同步到两个 contextvar：信封层 request_id_ctx + structlog 上下文
        rid_token = request_id_ctx.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        # 写入 scope state，供内层 OTel middleware 的 request_hook 挂到 server span
        # （本中间件在 OTel 外层，span 此刻尚未创建，不能直接 annotate）
        scope.setdefault("state", {})["request_id"] = request_id

        user_id = _best_effort_user_id(scope)
        if user_id:
            structlog.contextvars.bind_contextvars(user_id=user_id)

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                # 回显 request id，便于前端/网关报障对账
                headers = message.get("headers") or []
                headers.append(
                    (_REQUEST_ID_HEADER.encode(), request_id.encode())
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            self.log.info(
                "http.request",
                method=scope.get("method"),
                route=scope.get("path"),
                status=status_code,
                latency_ms=latency_ms,
                user_id=user_id or None,
                request_id=request_id,
            )
            structlog.contextvars.clear_contextvars()
            request_id_ctx.reset(rid_token)


def _header(scope: Scope, name: str) -> Optional[str]:
    """从 ASGI scope 读取请求头（name 为小写 bytes 键）。"""
    name_b = name.encode()
    for k, v in scope.get("headers", []):
        if k == name_b:
            return v.decode("latin-1", "replace")
    return None


def _best_effort_user_id(scope: Scope) -> Optional[str]:
    """仅用于日志的 JWT 解析：任何失败都静默返回 None，绝不影响请求鉴权。"""
    auth = _header(scope, "authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},  # 过期与否由鉴权依赖负责，这里只取 sub
        )
        sub = payload.get("sub")
        return str(sub) if sub else None
    except Exception:
        return None
