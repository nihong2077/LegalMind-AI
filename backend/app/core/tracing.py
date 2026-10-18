"""
OpenTelemetry 常开初始化（T0.7，Harness §7.4）

- FastAPI / httpx / SQLAlchemy / redis 自动埋点；
- W3C traceparent 传播（跨服务：API → litellm → 上游、API → worker 经 Kafka 时取 header）；
- OTLP gRPC 批量异步导出到 Jaeger；导出在后台线程，Jaeger 不可达**绝不阻断业务**；
- setup_tracing() 幂等；worker 进程复用同一函数（service_name 区分）。

接入位置（main.py）：
    setup_tracing()                 # 进程早期：全局 instrumentor + propagator
    app = FastAPI(...)
    ...include_router...
    instrument_app(app)             # 路由注册后、最外层包裹前
    app = RequestContextMiddleware(app)
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

from .config import settings

logger = logging.getLogger(__name__)

_initialized = False
_provider: Optional[TracerProvider] = None


def _grpc_endpoint(url: str) -> str:
    """OTLPSpanExporter(gRPC) 要 host:port；配置里统一写 http://host:port，这里归一。"""
    parsed = urlparse(url)
    if parsed.hostname:
        port = parsed.port or 4317
        return f"{parsed.hostname}:{port}"
    return url.strip()


def setup_tracing(
    *,
    enabled: Optional[bool] = None,
    service_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Optional[TracerProvider]:
    """初始化全局 TracerProvider、W3C propagator 与库自动埋点。幂等。

    - enabled=False：直接返回 None（不装 instrumentor，业务零开销）；
    - endpoint 指向不可达地址也安全：BatchSpanProcessor 后台线程导出，
      连接失败只重试/丢弃，不影响请求线程。
    """
    global _initialized, _provider
    if enabled is None:
        enabled = settings.OTEL_ENABLED
    if not enabled:
        logger.info("tracing.disabled")
        return None
    if _initialized:
        return _provider

    svc = service_name or settings.OTEL_SERVICE_NAME
    ep = _grpc_endpoint(endpoint or settings.OTEL_EXPORTER_OTLP_ENDPOINT)

    resource = Resource.create({"service.name": svc})
    provider = TracerProvider(resource=resource)
    # 批量异步导出：max_queue_size/延迟用默认；导出线程异常被 OTel 自身吞掉
    exporter = OTLPSpanExporter(endpoint=ep, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # W3C traceparent + baggage（默认上下文传播标准）
    set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )

    # 全局库埋点（幂等：instrumentor 自带状态判断，重复调用不报错）
    if not HTTPXClientInstrumentor().is_instrumented_by_opentelemetry:
        HTTPXClientInstrumentor().instrument()
    if not SQLAlchemyInstrumentor().is_instrumented_by_opentelemetry:
        SQLAlchemyInstrumentor().instrument()
    if not RedisInstrumentor().is_instrumented_by_opentelemetry:
        RedisInstrumentor().instrument()

    _initialized = True
    _provider = provider
    logger.info("tracing.initialised service=%s endpoint=%s", svc, ep)
    return provider


def _server_request_hook(span, scope) -> None:
    """server span 创建后回调（OTel ASGI 签名为 (span, scope)）：
    把最外层中间件写入 scope state 的 request_id 挂到 span 上，
    实现 Jaeger trace ↔ JSON 日志按 request_id 对账。"""
    try:
        rid = (scope.get("state") or {}).get("request_id")
        if rid and span and span.is_recording():
            span.set_attribute("request_id", rid)
    except Exception:
        pass


def instrument_app(app) -> None:
    """FastAPI app 埋点：必须在所有路由注册之后调用一次。

    与 T0.6 的 RequestContextMiddleware 共存：OTel 中间件进 FastAPI 内建栈
    （ServerErrorMiddleware 内侧），request-id 中间件仍在最外层包裹。
    """
    if not settings.OTEL_ENABLED:
        return
    # 默认不捕获请求/响应头（含 Authorization 与病历文本），避免敏感信息进 Jaeger
    FastAPIInstrumentor.instrument_app(app, server_request_hook=_server_request_hook)


def get_tracer(name: str):
    """业务代码需要自定义 span 时取 tracer（未初始化时由 API 返回 no-op tracer）。"""
    return trace.get_tracer(name)


def instrumentor_state() -> dict:
    """各库 instrumentor 安装状态（供健康检查/测试）。"""
    return {
        "httpx": HTTPXClientInstrumentor().is_instrumented_by_opentelemetry,
        "sqlalchemy": SQLAlchemyInstrumentor().is_instrumented_by_opentelemetry,
        "redis": RedisInstrumentor().is_instrumented_by_opentelemetry,
    }
