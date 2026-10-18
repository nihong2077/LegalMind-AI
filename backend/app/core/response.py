"""
统一响应信封（Harness §7.1）

成功：{"code": 0, "message": "ok", "data": {...}, "request_id": "req_xxx"}
失败：{"code": 40101, "message": "...", "detail": "...",
       "retryable": false, "request_id": "req_xxx"}

旧 29 个端点在 T0.12 前不穿信封：只有显式使用 EnvelopeRouter 的新路由
（或 raise BizException）才走信封；旧路由的 HTTPException/422/500 行为保持不变。
"""
from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings
from .errors import BizException, ErrorCode

logger = logging.getLogger(__name__)

# T0.6 的 request-id 中间件会在请求入口 set 此变量；
# 中间件落地前，get_request_id() 按需生成（同一 async task 内保持一致）。
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> str:
    rid = request_id_ctx.get()
    if not rid:
        rid = "req_" + uuid.uuid4().hex[:12]
        request_id_ctx.set(rid)
    return rid


class ApiResponse(BaseModel):
    """信封文档模型（实际响应由 success/error 工厂构造为 dict）"""
    code: int
    message: str
    request_id: str
    data: Any = None
    detail: Any = None
    retryable: Optional[bool] = None


def success(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data, "request_id": get_request_id()}


def error(
    error_code: ErrorCode,
    message: Optional[str] = None,
    detail: Any = None,
    *,
    retryable: Optional[bool] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": error_code.code,
        "message": message or error_code.message,
        "request_id": get_request_id(),
        "retryable": error_code.retryable if retryable is None else retryable,
    }
    if detail is not None:
        body["detail"] = detail
    return body


# ============================================================
# 新路由标记：EnvelopeRouter 上的所有端点统一穿信封
# ============================================================

async def _mark_envelope(request: Request) -> None:
    request.state.use_envelope = True


def EnvelopeRouter(**kwargs) -> APIRouter:
    """新业务路由工厂：自动给请求打 use_envelope 标记。

    用法::

        router = EnvelopeRouter(prefix="/conversations", tags=["会话"])
    """
    kwargs.setdefault("dependencies", []).append(Depends(_mark_envelope))
    return APIRouter(**kwargs)


# FastAPI/Starlette HTTP 状态 → 新路由信封错误码
_HTTP_TO_ERROR = {
    400: ErrorCode.INVALID_PARAMS,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    429: ErrorCode.RATE_LIMITED,
}


def _is_envelope_request(request: Request) -> bool:
    return bool(getattr(request.state, "use_envelope", False))


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器（在 main.py 调用一次）。

    - BizException：始终信封（仅新代码会抛出）
    - HTTPException / 422 / 未捕获异常：仅 EnvelopeRouter 路由走信封，
      旧路由复刻 FastAPI/Starlette 默认响应，T0.12 前行为零变化。
    """

    @app.exception_handler(BizException)
    async def _biz_exception_handler(request: Request, exc: BizException):
        logger.warning(
            "业务异常 code=%s %s path=%s request_id=%s detail=%s",
            exc.code, exc.message, request.url.path,
            get_request_id(), exc.detail,
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=error(exc.error_code, exc.message, exc.detail,
                          retryable=exc.retryable),
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        if not _is_envelope_request(request):
            # 复刻 FastAPI 默认行为（含 401 的 WWW-Authenticate 头）
            headers = getattr(exc, "headers", None)
            return JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=headers
            )
        ec = _HTTP_TO_ERROR.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        detail = exc.detail if isinstance(exc.detail, str) else jsonable_encoder(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error(ec, detail=str(detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        if not _is_envelope_request(request):
            # FastAPI 默认 422 形状
            return JSONResponse(
                status_code=422,
                content={"detail": jsonable_encoder(exc.errors())},
            )
        return JSONResponse(
            status_code=400,
            content=_validation_error_body(exc),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        rid = get_request_id()
        logger.exception("未捕获异常 path=%s request_id=%s", request.url.path, rid)
        if not _is_envelope_request(request):
            # 复刻 T0.12 前旧 global_exception_handler 的兜底响应
            # （LEGACY_RESPONSE=true 时等价；默认信封模式下由
            # LegacyEnvelopeMiddleware 再包成 50000 错误信封）。
            return JSONResponse(
                status_code=500,
                content={"detail": "服务器内部错误", "type": type(exc).__name__},
            )
        return JSONResponse(
            status_code=500,
            content=error(ErrorCode.INTERNAL_ERROR, detail=rid),
        )


def _validation_error_body(exc: RequestValidationError) -> dict[str, Any]:
    """422 校验错误转 40001 信封，detail 保留字段级错误。"""
    errs = jsonable_encoder(exc.errors())
    first = errs[0] if errs else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    msg = first.get("msg", "请求参数错误")
    message = f"参数错误：{loc} {msg}".strip() if loc else msg
    return error(ErrorCode.INVALID_PARAMS, message=message, detail=errs)


# HTTP 状态码（保留原语义，T0.12 不改状态码）→ 信封业务码
_STATUS_TO_ERROR: dict[int, ErrorCode] = {ec.http_status: ec for ec in (
    ErrorCode.INVALID_PARAMS,   # 400
    ErrorCode.UNAUTHORIZED,     # 401
    ErrorCode.FORBIDDEN,        # 403
    ErrorCode.NOT_FOUND,        # 404
    ErrorCode.CONFLICT,         # 409
    ErrorCode.RATE_LIMITED,     # 429
    ErrorCode.INTERNAL_ERROR,   # 500
    ErrorCode.LLM_CALL_FAILED,  # 502
    ErrorCode.CIRCUIT_OPEN,     # 503
    ErrorCode.UPSTREAM_TIMEOUT, # 504
)}
# 422（FastAPI 入参校验）在旧 HTTP 语义下保留 422 状态码，业务码复用 40001
_STATUS_TO_ERROR[422] = ErrorCode.INVALID_PARAMS
# 405/413/415 等未细分错误码统一归 40001
_STATUS_TO_ERROR.setdefault(405, ErrorCode.INVALID_PARAMS)


def _first_validation_message(errors: list[Any]) -> str:
    first = errors[0] if errors else {}
    if isinstance(first, dict):
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = first.get("msg", "请求参数错误")
        return f"参数错误：{loc} {msg}".strip() if loc else str(msg)
    return "请求参数错误"


def _envelope_error_body(status: int, payload: Any) -> dict[str, Any]:
    """把旧错误响应体（{"detail": ...} 等）转信封错误体，HTTP 状态码不变。"""
    ec = _STATUS_TO_ERROR.get(status)
    if ec is None:
        ec = ErrorCode.INVALID_PARAMS if status < 500 else ErrorCode.INTERNAL_ERROR
    message: Optional[str] = None
    detail: Any = None
    if isinstance(payload, dict) and "detail" in payload:
        raw_detail = payload["detail"]
        if isinstance(raw_detail, str):
            message = raw_detail
        elif isinstance(raw_detail, list):  # 422 字段级错误
            message = _first_validation_message(raw_detail)
            detail = raw_detail
        elif raw_detail is not None:
            message = str(raw_detail)
    elif isinstance(payload, str) and payload:
        message = payload
    if status >= 500 and detail is None:
        # 5xx 不把内部细节塞进 message；request_id 供后端日志对账
        detail = get_request_id()
    return error(ec, message=message, detail=detail)


class LegacyEnvelopeMiddleware:
    """旧 29 端点（/api/* 下所有非 SSE JSON 响应）统一穿信封。

    - 成功：原负载整体下沉 ``data``，HTTP 状态码不变；
    - 失败：按原 HTTP 状态码映射业务码，原 ``detail`` 转 message/detail；
    - SSE（text/event-stream）与非 JSON 响应原样透传；
    - 已是信封（含 code+request_id）不重复包裹；
    - ``settings.LEGACY_RESPONSE=True`` 时整体透传（一键回滚）。

    request_id 复用外层 RequestContextMiddleware 绑定的同一 contextvar，
    故信封体 request_id 与 X-Request-ID 响应头必然一致。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or settings.LEGACY_RESPONSE
            or not scope.get("path", "").startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        start_msg: Optional[Message] = None
        body_chunks: list[bytes] = []
        # 一旦判定透传（SSE/204 等），把已缓存的 start 与后续分片按序直发
        passthrough = False

        async def send_wrapper(message: Message) -> None:
            nonlocal start_msg, passthrough
            if message["type"] == "http.response.start":
                start_msg = message
                if self._should_passthrough(message):
                    passthrough = True
                    await send(message)
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            if passthrough or start_msg is None:
                await send(message)
                return
            body_chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            await self._emit(send, start_msg, b"".join(body_chunks))

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _should_passthrough(start: Message) -> bool:
        status = start.get("status", 0)
        if status in (204, 304):
            return True
        for k, v in start.get("headers", []):
            if k == b"content-type" and b"text/event-stream" in v:
                return True
        return False

    @staticmethod
    def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> Optional[bytes]:
        for k, v in headers:
            if k == name:
                return v
        return None

    async def _emit(
        self, send: Send, start: Message, raw_body: bytes
    ) -> None:
        status = start.get("status", 200)
        headers = list(start.get("headers", []))
        ctype = self._header(headers, b"content-type") or b""
        is_json = b"application/json" in ctype

        new_body: Optional[bytes] = None
        if is_json and raw_body:
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = None
            # 已是信封（BizException 处理器/新路由）不重复包裹
            if isinstance(payload, dict) and "code" in payload and "request_id" in payload:
                new_body = raw_body
            elif status < 400:
                new_body = json.dumps(
                    success(payload), ensure_ascii=False,
                ).encode("utf-8")
            else:
                new_body = json.dumps(
                    _envelope_error_body(status, payload),
                    ensure_ascii=False,
                ).encode("utf-8")
        elif not is_json and status >= 400:
            # Starlette 兜底的纯文本 500 等，同样补信封
            new_body = json.dumps(
                _envelope_error_body(status, None),
                ensure_ascii=False,
            ).encode("utf-8")

        if new_body is not None:
            headers = [
                (k, v) for k, v in headers
                if k not in (b"content-length", b"content-type")
            ]
            headers.append((b"content-type", b"application/json; charset=utf-8"))
            headers.append((b"content-length", str(len(new_body)).encode()))

        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": new_body if new_body is not None else raw_body})


# ============================================================
# SSE error 事件统一形状（T0.12；三类旧形状归一）
# ============================================================

def sse_error_event(
    error_code: ErrorCode = ErrorCode.LLM_CALL_FAILED,
    message: Optional[str] = None,
    detail: Optional[str] = None,
    *,
    retryable: Optional[bool] = None,
) -> dict[str, str]:
    """构造统一的 SSE error 事件。

    data 形状::

        {"code": 50201, "message": "AI 服务暂不可用…", "error": "<原始异常>",
         "detail": ..., "retryable": true, "request_id": "req_xxx"}

    ``error`` 字段为兼容旧前端保留（=detail/message）。
    """
    msg = message or error_code.message
    data: dict[str, Any] = {
        "code": error_code.code,
        "message": msg,
        "error": detail or msg,
        "retryable": error_code.retryable if retryable is None else retryable,
        "request_id": get_request_id(),
    }
    if detail:
        data["detail"] = detail
    return {"event": "error", "data": json.dumps(data, ensure_ascii=False)}
