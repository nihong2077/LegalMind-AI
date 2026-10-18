"""T0.7 OpenTelemetry：span 串联、W3C traceparent 注入、关 Jaeger 不阻断、幂等。"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import sys
sys.path.insert(0, ".")

from app.core.logging import RequestContextMiddleware  # noqa: E402
from app.core.tracing import (  # noqa: E402
    _grpc_endpoint,
    instrument_app,
    instrumentor_state,
    setup_tracing,
)

# 末段为 trace flags 两位 hex：01=sampled，03=sampled+random(OTel 1.45 默认)
TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


# ---------- 纯函数 ----------

@pytest.mark.parametrize("raw,expected", [
    ("http://jaeger:4317", "jaeger:4317"),
    ("http://jaeger", "jaeger:4317"),       # 缺省端口补 4317
    ("https://otel.local:443", "otel.local:443"),
    ("127.0.0.1:4317", "127.0.0.1:4317"),  # 已是 host:port
])
def test_grpc_endpoint_normalize(raw, expected):
    assert _grpc_endpoint(raw) == expected


# ---------- 本地真实 HTTP 下游（MockTransport 不被 httpx instrumentor 包装，
#            故用真实 socket，走 AsyncHTTPTransport 完整注入路径） ----------

class _Downstream(BaseHTTPRequestHandler):
    last_traceparent = ""

    def do_GET(self):
        _Downstream.last_traceparent = self.headers.get("traceparent", "")
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def downstream_server():
    srv = HTTPServer(("127.0.0.1", 0), _Downstream)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


# ---------- 一次性初始化（指向不可达 OTLP，验证不阻断） ----------

@pytest.fixture(scope="module")
def tracer_setup():
    # 127.0.0.1:1 无服务；BatchSpanProcessor 后台导出失败不得影响请求线程
    provider = setup_tracing(
        service_name="legalmind-test",
        endpoint="http://127.0.0.1:1",
    )
    assert provider is not None
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    return provider, memory


def _build_wrapped_app(base_url: str):
    """FastAPI 端点内用 httpx 默认 transport 发一次真实下游调用（生产 llm_client 同款）。"""
    app = FastAPI()

    @app.get("/downstream")
    async def downstream():
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base_url}/v1/ping")
        return {"child_status": r.status_code}

    instrument_app(app)
    # 与生产一致：request-id 中间件最外层
    return RequestContextMiddleware(app)


def test_full_trace_chain_and_unreachable_jaeger(tracer_setup, downstream_server):
    provider, memory = tracer_setup
    memory.clear()
    _Downstream.last_traceparent = ""
    client = TestClient(_build_wrapped_app(downstream_server))

    r = client.get("/downstream", headers={"X-Request-ID": "req_otel_demo_01"})

    # 1) Jaeger 不可达，业务照常
    assert r.status_code == 200 and r.json()["child_status"] == 200

    # 2) 下游真实收到 W3C traceparent
    assert TRACEPARENT_RE.match(_Downstream.last_traceparent), \
        _Downstream.last_traceparent

    # 3) server span 与 httpx client span 同 trace、父子相接
    spans = memory.get_finished_spans()
    server_spans = [
        s for s in spans
        if s.instrumentation_scope and "fastapi" in (s.instrumentation_scope.name or "")
        and s.kind == trace.SpanKind.SERVER
    ]
    client_spans = [s for s in spans if s.kind == trace.SpanKind.CLIENT]
    assert len(server_spans) == 1, [s.name for s in spans]
    assert client_spans, "应有 httpx client span"

    server_ctx = server_spans[0].context
    httpx_span = client_spans[-1]
    assert httpx_span.context.trace_id == server_ctx.trace_id          # 同一 trace
    assert httpx_span.parent.span_id == server_ctx.span_id             # 父子相接

    # 4) request_id 经 server_request_hook 挂到 server span（trace↔日志对账）
    assert server_spans[0].attributes["request_id"] == "req_otel_demo_01"

    # 5) 注入下游的 traceparent 与 server span 的 trace_id 一致
    tp_trace_id = _Downstream.last_traceparent.split("-")[1]
    assert f"{server_ctx.trace_id:032x}" == tp_trace_id


def test_instrumentors_installed(tracer_setup):
    state = instrumentor_state()
    assert state["httpx"] is True
    assert state["sqlalchemy"] is True
    assert state["redis"] is True


def test_setup_tracing_idempotent(tracer_setup):
    provider, _ = tracer_setup
    assert setup_tracing() is provider  # 重复调用返回同一实例，不重复 instrument


def test_disabled_returns_none():
    assert setup_tracing(enabled=False) is None
