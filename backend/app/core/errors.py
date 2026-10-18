"""
统一错误码与业务异常（Harness §7.1）

错误码段位：
  0      成功
  40xxx  入参 / 认证 / 限流（40101 未认证、40102 token 过期、42901 限流、50901 轮次锁冲突）
  50xxx  服务端（50201 LLM 失败、50301 熔断中、50310 Kafka 降级、50401 超时）

每个错误码自带 HTTP 状态与 retryable（前端对 retryable=true 展示"重试"按钮）。
SSE error 事件复用同一组错误码（T0.12 统一）。
"""
from __future__ import annotations

import enum
from typing import Optional


class ErrorCode(enum.Enum):
    # (业务码, HTTP 状态, retryable, 默认文案)
    SUCCESS = (0, 200, False, "ok")

    # ---- 40xxx 客户端侧 ----
    INVALID_PARAMS = (40001, 400, False, "请求参数错误")
    NOT_FOUND = (40004, 404, False, "资源不存在")
    CONFLICT = (40009, 409, False, "资源冲突")
    UNAUTHORIZED = (40101, 401, False, "未登录或登录已失效")
    TOKEN_EXPIRED = (40102, 401, False, "登录已过期，请重新登录")
    FORBIDDEN = (40301, 403, False, "无权访问该资源")
    RATE_LIMITED = (42901, 429, True, "请求过于频繁，请稍后重试")
    # 同一会话上一轮会商仍在进行（T1.1 轮次锁；客户端可稍后重试）
    TURN_LOCK_CONFLICT = (50901, 409, True, "会商进行中，请稍候再发送")

    # ---- 50xxx 服务端侧 ----
    INTERNAL_ERROR = (50000, 500, False, "服务内部错误")
    LLM_CALL_FAILED = (50201, 502, True, "AI 服务暂不可用，请稍后重试")
    CIRCUIT_OPEN = (50301, 503, True, "服务熔断中，请稍后重试")
    # Kafka 不可用已降级到进程内编排——正常不抛给用户，仅用于日志/指标码
    KAFKA_DEGRADED = (50310, 503, False, "消息队列不可用，已降级为本地处理")
    UPSTREAM_TIMEOUT = (50401, 504, True, "上游服务响应超时，请稍后重试")

    def __init__(self, code: int, http_status: int, retryable: bool, message: str):
        self.code = code
        self.http_status = http_status
        self.retryable = retryable
        self.message = message


class BizException(Exception):
    """业务异常基类：全局处理器统一转信封响应。

    新路由（EnvelopeRouter）raise 本异常；旧路由继续用 FastAPI HTTPException，
    在 T0.12 全量切换前其响应形状保持 ``{"detail": ...}`` 不变。
    """

    def __init__(
        self,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        message: Optional[str] = None,
        detail: Optional[str] = None,
        *,
        retryable: Optional[bool] = None,
    ):
        self.error_code = error_code
        self.code = error_code.code
        self.http_status = error_code.http_status
        self.message = message or error_code.message
        self.detail = detail
        self.retryable = error_code.retryable if retryable is None else retryable
        super().__init__(self.message)


# ============================================================
# 快捷异常：新路由业务代码直接 raise
# ============================================================

class InvalidParamsError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.INVALID_PARAMS, message=message, detail=detail)


class NotFoundError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.NOT_FOUND, message=message, detail=detail)


class ConflictError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.CONFLICT, message=message, detail=detail)


class UnauthorizedError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.UNAUTHORIZED, message=message, detail=detail)


class TokenExpiredError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.TOKEN_EXPIRED, message=message, detail=detail)


class ForbiddenError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.FORBIDDEN, message=message, detail=detail)


class RateLimitedError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.RATE_LIMITED, message=message, detail=detail)


class TurnLockConflictError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.TURN_LOCK_CONFLICT, message=message, detail=detail)


class LLMCallFailedError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.LLM_CALL_FAILED, message=message, detail=detail)


class CircuitOpenError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.CIRCUIT_OPEN, message=message, detail=detail)


class UpstreamTimeoutError(BizException):
    def __init__(self, message: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(ErrorCode.UPSTREAM_TIMEOUT, message=message, detail=detail)
