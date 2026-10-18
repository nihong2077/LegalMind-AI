"""
Prometheus 指标集中定义（T0.11）

覆盖计划清单：http / llm / retry / cb（resilience.py 已埋，此处统一 re-export）/
kafka(publish+consumer_lag) / worker heartbeat / collab turn / agent。

约定：
- label 基数可控：HTTP path 用**路由模板**（/api/x/{id}），未匹配路由记 ``unmatched``；
- 全部注册进 prometheus_client 默认 REGISTRY，``/metrics`` 直接 generate_latest；
- turn/agent 为本卡预置（P1 协同业务接入时 .labels().inc()），看板（T3.4）即取即用。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from prometheus_client import Counter, Gauge, Histogram

# retry/cb 在 T0.5 已埋点，re-export 形成单一 import 面（同名对象，不重复注册）
from .resilience import CIRCUIT_REJECTED_TOTAL, CIRCUIT_STATE, RETRY_TOTAL

# ---------------- HTTP（ASGI 中间件自动埋） ----------------

HTTP_REQUESTS = Counter(
    "legalmind_http_requests_total",
    "HTTP 请求总数",
    labelnames=("method", "path", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "legalmind_http_request_duration_seconds",
    "HTTP 请求处理耗时（含 SSE 全流时长）",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# ---------------- LLM（llm_client 埋） ----------------

LLM_REQUESTS = Counter(
    "legalmind_llm_requests_total",
    "LLM 调用次数",
    labelnames=("model", "service", "mode", "status"),
)
LLM_REQUEST_DURATION = Histogram(
    "legalmind_llm_request_duration_seconds",
    "LLM 调用耗时（stream 模式为首字节时间）",
    labelnames=("model", "service", "mode"),
)

# ---------------- Kafka（events.py / worker 埋） ----------------

KAFKA_PUBLISH = Counter(
    "legalmind_kafka_publish_total",
    "Kafka 生产结果计数",
    labelnames=("topic", "result"),  # result=enqueued/disabled/degraded
)
KAFKA_CONSUMER_MESSAGES = Counter(
    "legalmind_kafka_consumer_messages_total",
    "Kafka 消费到的消息条数",
    labelnames=("group", "topic"),
)
KAFKA_CONSUMER_LAG = Gauge(
    "legalmind_kafka_consumer_lag",
    "Kafka 消费组各分区积压条数",
    labelnames=("group", "topic", "partition"),
)

# ---------------- Worker 心跳 ----------------

WORKER_HEARTBEAT_TS = Gauge(
    "legalmind_worker_heartbeat_timestamp",
    "worker 最后一跳 epoch 秒",
    labelnames=("role", "worker_id"),
)
WORKER_ONLINE = Gauge(
    "legalmind_worker_online",
    "worker 在线标记（1=本进程正在心跳）",
    labelnames=("role", "worker_id"),
)

# ---------------- 协同（P1 业务接入，本卡仅预置） ----------------

COLLAB_TURN = Counter(
    "legalmind_collab_turn_total",
    "协同回合终态计数",
    labelnames=("state",),  # completed/interrupted/failed
)
COLLAB_TURN_ORPHAN = Counter(
    "legalmind_collab_turn_orphan_total",
    "被认领续跑的僵死轮次计数（worker 崩溃接力，T1.6 §3.2）",
    labelnames=("result",),  # recovered/skipped
)
AGENT_RUN = Counter(
    "legalmind_agent_run_total",
    "Agent 节点执行次数",
    labelnames=("agent", "status"),
)
AGENT_RUN_DURATION = Histogram(
    "legalmind_agent_run_duration_seconds",
    "Agent 节点执行耗时",
    labelnames=("agent",),
)

# ---------------- 联网检索（DeepSeek tools：Search/Fetch，P2-WebSearch） ----------------

WEB_SEARCH_CALLS = Counter(
    "legalmind_web_search_calls_total",
    "联网检索调用计数",
    labelnames=("op", "mode", "status"),  # op=search/fetch; mode=proxy/direct; status=success/retry/error
)

# ---------------- 长期记忆自动抽取（T2.2） ----------------

MEMORY_INGEST = Counter(
    "legalmind_memory_ingest_total",
    "记忆写入管线终态计数",
    labelnames=("result",),  # ok/skipped/dlq/error
)
MEMORY_EXTRACT = Counter(
    "legalmind_memory_extract_total",
    "候选记忆处理动作计数",
    labelnames=("action",),  # merge/prompt/new
)


# ============================================================
# HTTP 指标 ASGI 中间件（轻量纯 ASGI，位于 RequestContext 内侧）
# ============================================================

def _route_template(scope: dict) -> str:
    """优先取路由模板（低基数）；未匹配 404 一律记 unmatched。"""
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    return scope.get("path_template") or "unmatched"


class PrometheusASGIMiddleware:
    """记录 HTTP 请求计数/状态码/耗时。自身不吞异常：交由外层统一异常链。"""

    def __init__(self, app: Any, exclude: tuple[str, ...] = ("/metrics",)):
        self.app = app
        self.exclude = exclude

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in self.exclude:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        start = time.perf_counter()
        status_code = 500
        is_stream = False

        async def _send(message):
            nonlocal status_code, is_stream
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # SSE 长流生命周期=工作流时长（常达数分钟），计入普通 HTTP
                # 延迟直方图会全部落入 +Inf 桶、污染分位数；只保留计数。
                for k, v in message.get("headers", []):
                    if k == b"content-type" and b"text/event-stream" in v:
                        is_stream = True
                        break
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            path = _route_template(scope)
            HTTP_REQUESTS.labels(method, path, str(status_code)).inc()
            if not is_stream:
                HTTP_REQUEST_DURATION.labels(method, path).observe(
                    time.perf_counter() - start
                )


# ============================================================
# Kafka lag 采集（worker 待命/消费循环周期调用）
# ============================================================

async def record_kafka_lag(consumer: Any, group: str) -> None:
    """读取 consumer 分配分区的 end offset 与当前 position，更新 lag gauge。

    消费组成员分区重平衡期间 assignment 可能为空，直接跳过。
    """
    partitions = list(consumer.assignment())
    if not partitions:
        return
    end_offsets = await consumer.end_offsets(partitions)
    for tp in partitions:
        position = await consumer.position(tp)
        # 尚未提交/未定位时 position 为 -1（earliest 语义下相当于全量积压）
        pos = position if position is not None and position >= 0 else 0
        lag = max(0, end_offsets.get(tp, 0) - pos)
        KAFKA_CONSUMER_LAG.labels(
            group=group, topic=tp.topic, partition=str(tp.partition)
        ).set(lag)
