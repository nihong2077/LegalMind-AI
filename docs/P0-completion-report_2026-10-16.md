# P0 工程地基 — 完成报告（T0.1–T0.12）

- 报告日期：2026-10-16
- 范围：`docs/collab-implementation_plan.md` P0 全部 12 张任务卡
- 镜像：`legalmind-backend:local`（2026-10-16 重建，含全部修复；Python 3.12.15）
- 结论：**P0 完成。** 后端 154 项测试全绿，信封/SSE/探针/worker 经真机验收，一键回滚开关有效，两条回归红线的服务端行为已验证；前端生产构建通过，建议人工再点一遍浏览器三栏/补证流（服务已起在 :3100）。

---

## 1. 总览

| 卡 | 任务 | 状态 | 关键证据（2026-10-16 真机/全量测试） |
|---|---|---|---|
| T0.1 | 版本与镜像对齐（py3.12 + 锁依赖 + aiokafka/tenacity/structlog/OTel 等） | ✅ | 镜像构建成功；容器内 `pip check` → `No broken requirements found`，Python 3.12.15 |
| T0.2 | 第四库 + 04-app-schema（8 表）+ 10 Agent/8 模板种子 | ✅ | 四库实存 `judge_db/lawyer_db/law_db/legalmind_app`；`agent_registry=10`、`case_roster_templates=8`（psql 实查） |
| T0.3 | pg_client 第四引擎 app_engine + ORM | ✅ | API 容器以 4 个 PG_URL 启动成功；`/readyz` 四库全 healthy |
| T0.4 | 统一信封与错误码（response.py / errors.py / 全局处理器） | ✅ | 真机错误码：401→40101、404→40004、422→40001、LLM 失败→50201；信封专项 18 测试 |
| T0.5 | resilience：tenacity 重试/超时分层/熔断/降级 | ✅ | `is_retryable` 对 Read/Write/Close/ConnectError 分类实测通过；真机 SSE 50201 `retryable=true`；熔断类测试通过 |
| T0.6 | structlog JSON + X-Request-ID（contextvar 贯穿） | ✅ | 真机：响应头 `X-Request-ID` 与信封体 `request_id` 完全一致（多次请求一致 ✓） |
| T0.7 | OTel 常开 + W3C traceparent + jaeger | ✅ 配置就位 | compose 含 jaeger:1.60 服务；OTel 关闭时业务正常（今日冒烟以 OTEL_ENABLED=false 运行）；trace 链路在 T0.7 验收时已确认 |
| T0.8 | Kafka KRaft + 3 topic×3 分区 + aiokafka 懒连/降级 + 开关 | ✅ | 今日实起 KRaft broker，创建 `collab-turns/memory-events/doc-tasks`（各 3 分区）；`ENABLE_KAFKA=false` 下 API 日志 "事件走进程内降级" 正常 |
| T0.9 | LangGraph AsyncPostgresSaver（legalmind_app） | ✅ | 实库存在 `checkpoints/checkpoint_writes/checkpoint_blobs/checkpoint_migrations` 四表 |
| T0.10 | Worker 骨架（--role collab/memory/doc、:8001、心跳、优雅停机） | ✅ | 今日两种模式真机冒烟，见 §3；SIGTERM 退出码 0，日志 `stopping→consumer_stopped→stopped` |
| T0.11 | /healthz、/readyz、Prometheus 指标补齐 | ✅ | 断 Redis：healthz=200、readyz=503（redis=unhealthy，postgres=healthy）；恢复后 readyz=200；/metrics 裸 Prometheus 文本不穿信封 |
| T0.12 | 旧 29 端点全量穿信封 + 三类 SSE error 统一 + 前端 http.ts | ✅ | 见 §2 专项证据 |

## 2. T0.12 专项验收证据

### 2.1 信封（容器 `legalmind-api-t12`，默认 `LEGACY_RESPONSE=false`）

| 场景 | 方法/端点 | HTTP | 实测响应（节选） |
|---|---|---|---|
| 成功下沉 data | POST `/api/auth/token`（admin/admin） | 200 | `{"code":0,"message":"ok","data":{"access_token":"…","token_type":"bearer","username":"admin"},"request_id":"req_a6d0…"}` |
| 列表负载 | GET `/api/dashboard/stats` | 200 | `{"code":0,…,"data":{"chat_count":0,"doc_count":0,"knowledge_count":2450,"efficiency_gain":"+45%"}}` |
| 对象负载 | GET `/api/models` | 200 | `data.models[]` 下沉正常 |
| 未认证 | GET `/api/models` 无 token | 401 | `{"code":40101,"message":"Not authenticated",…,"retryable":false}` |
| 业务 404 | GET `/api/tasks/nope-x`（真 token） | 404 | `{"code":40004,"message":"任务不存在",…}` |
| 入参校验 | POST `/api/knowledge/search` 空 body | 422 | `{"code":40001,"message":"参数错误：query Field required","detail":[…字段级…]}`，**HTTP 语义保留 422** |
| request_id 一致 | 登录响应头/体比对 | — | 头 `X-Request-ID` == 体 `request_id`（req_a6d05a57925a 两边相等 ✓） |
| 非 /api 透传 | GET `/healthz`、`/`、`/metrics` | 200 | 分别为裸 `{"status":"ok"}`、裸版本 JSON、Prometheus 文本，均不穿信封 |

### 2.2 SSE error 统一（三类旧形状收口）

POST `/api/chat/stream`（无 LLM key 的失败场景，真机）：

```
event: status  data: {"phase":"retrieving", ...}
event: status  data: {"phase":"generating", ...}
event: error   data: {"code":50201,"message":"AI 服务暂时不可用，请稍后重试",
                      "error":"Illegal header value b'Bearer '",
                      "retryable":true,"request_id":"req_c619…","detail":"…"}
```

- 字段齐：`code/message/error（兼容旧前端）/detail/retryable/request_id`。
- **分片鲁棒性**：用 Node 20 fetch 打活后端、把字节流强制按 3 字节切碎喂入与前端同款"事件块"解析器，事件序列正确解析为 `status → status → error`，无事件名丢失（修复了旧解析器 event:/data: 跨 TCP chunk 丢事件名的真实缺陷）。
- 后端 4 处 SSE 出口（chat/stream、agents/stream、debate/stream、contract/review/stream）与 `/api/stream/{task_id}` failed 分支全部改走 `sse_error_event()`；正常事件形状（status/message/metadata/done）未改动。

### 2.3 一键回滚

`LEGACY_RESPONSE=true` 第二实例（:8002）：

| 端点 | 实测 |
|---|---|
| `/api/models` 未认证 | `{"detail":"Not authenticated"}`（旧形状，无信封） |
| 无效 token | `{"detail":"无效 Token"}` |
| `/healthz` | `{"status":"ok"}` |

### 2.4 前端

- 运行时：工作区自带 Node `v20.20.2`（`.nvm`），`next build`（Next 14.2.35）**✓ Compiled successfully，11/11 静态页生成**，`tsc --noEmit` EXIT=0。
- `app/lib/http.ts`（新）：信封解包、ApiError、401 仅在本地确有失效 token 时清凭证跳登录（避免登录接口密码错误也被强制跳页/覆盖服务端消息）、429/502/503/504 仅幂等方法或带 Idempotency-Key 重试、遵守 Retry-After、AbortError 不重试、非信封响应原样返回（兼容回滚期）。
- `app/lib/api.ts`：导出名/接口名零变更，调用方页面零改动；SSE 解析器重写为按 `\n\n` 事件块解析（兼容 CRLF、无空格 `event:` 写法、跨 chunk）。
- 页面冒烟（`next start` :3100）：`/login /court /documents /dashboard /chat /knowledge /cases` 全部 200；合同审查入口挂在 `/documents`（DocumentUpload → contractReviewStream，事件集 metadata/message/done/error 与后端一致）；庭审 `/court` → debateStream（补证靠 metadata/done 的 `evidence_sufficient/evidence_needed` 字段与请求体 `evidence_supplemented`，均未变）。
- `/api/agents/stream` 当前前端无调用方（P1 能力），其 analysis/review/research 事件不影响红线。

## 3. Worker harness（P0 完成标志）

| 模式 | 今日实测 |
|---|---|
| `ENABLE_KAFKA=false` | `python -m app.worker.main --role collab` 起停正常；`/healthz` 200 返回 role/worker_id/uptime；Redis 心跳键 `legalmind:worker:<id>`（EX 30）与 ZSET `legalmind:workers:online` 均有成员；`worker_heartbeat_timestamp` 指标在采 |
| `ENABLE_KAFKA=true` | 实起 KRaft broker + 3 topic 后，worker 自动入组 `legalmind-worker-collab`，获派 collab-turns 全 3 分区，日志 `worker.standby topic=collab-turns`，`kafka_consumer_lag{partition=0/1/2}=0` —— **空转待命成立** |
| 优雅停机 | SIGTERM：`worker.stopping → worker.consumer_stopped → worker.stopped`，退出码 0（start 失败路径同样显式 stop consumer，修复了任务泄漏） |

## 4. 本轮全量审视发现并修复的缺陷

| 级别 | 缺陷 | 修复 |
|---|---|---|
| P1 | `main.py` lifespan for-else 中裸 `raise`（无活跃异常时会变 RuntimeError） | 保存 `last_exc/pg_last_exc` 后显式 `raise last_exc` |
| P1 | 本地模式 qdrant 冷构造（磁盘加载约 60s）阻塞事件循环，探针路径可能被击穿 | `aget_qdrant_client()` 走 `asyncio.to_thread`+双检锁；health 探针用 `get_qdrant_client_or_none()`，绝不在探针路径冷构造 |
| P2 | worker consumer start 失败/超时无 stop 清理 | `started` 标志 + 失败路径 `wait_for(stop(),5)`，finally 仅在 started 时 stop |
| P2 | 流式 LLM 调用缺总重试预算、TransportError 无兜底 | `open_resilient_stream` 加 `LLM_RETRY_DEADLINE`（首字节前 monotonic 预算，退避受剩余时间限制）；`with_resilience` 加 httpx.TransportError 兜底分支 |
| P2 | `chat_count` 的 `r.incr` 与业务成功路径同 try，计数失败会误触发 record_failure/补发 SSE error | 计数独立 try/except，仅 warning |
| P2 | 滑动窗限流器被拒请求也写 zset，持续重试会被"永久锁死" | 先 zcard 判断，放行才 zadd |
| P2 | `/api/stream/{task_id}` while 循环无异常兜底 | 整体 try/except；CancelledError re-raise，其余补发统一 error 事件 |
| P2 | EventBus `close()` 与 `publish()` 竞态（停机窗口可重建生产者） | 加 `_closed` 标志，关闭后拒绝懒连 |
| P2 | SSE 长流生命周期计入 HTTP 延迟直方图，样本全落 +Inf 污染分位 | 中间件识别 `text/event-stream`，只计数不 observe 延迟（真机确认 chat/stream 仅出现在 requests 指标） |
| P2 | LLM 缓存命中无指标 | 命中记 `llm_requests{service="cache",status="cache_hit"}` |
| P2（前端，新发现） | SSE 解析器 `currentEvent` 在 chunk 循环内重置，TCP 分片把 event:/data: 拆开时事件名丢失（统一 error 事件可能被静默吞掉） | 重写为事件块解析，真机强制 3 字节分片验证通过 |
| P2（前端，新发现） | 登录接口密码错误（401）也会清凭证跳登录页，且服务端错误消息被固定文案覆盖 | 仅本地持有失效 token 时才跳转；消息保留服务端原文 |
| — | 旧 `global_exception_handler` 覆盖 T0.4 信封兜底（T0.6 遗留） | 删除旧 handler 与 `EXCEPTION_STATUS_MAP`；旧路由 500 由处理器复刻旧形状后再由信封中间件包装；中间件链实测固定为 Client→RequestContext→Prometheus→Envelope→OTel→ServerError→路由 |

## 5. 测试与构建汇总

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `backend/venv/bin/python -m pytest -q` | **154 passed**（12 个测试文件；含 `tests/test_envelope_legacy.py` 18 项） |
| 镜像依赖 | 容器内 `pip check` | No broken requirements found |
| 前端类型 | `tsc --noEmit`（Node 20.20.2） | EXIT=0 |
| 前端构建 | `next build` | ✓ 11/11 页面，全部路由 200 冒烟 |
| 磁盘 | `docker image prune` + 旧标签/废弃容器清理 | 回收 28.11GB；误下的临时 Node 已删（项目自带 .nvm Node20） |

## 6. 遗留项与风险

1. **浏览器人工点击仍建议做**：服务端信封/SSE/分片已自动化验证，但合同审查"三栏 UI 联动"与庭审"补证后二轮辩论"的像素级交互需人工过一遍。生产服务已在本机 `http://localhost:3100`（→ 后端 :8000，admin/admin）。
2. **LLM happy-path 未真机跑通**：当前环境无 `DEEPSEEK_API_KEY`（失败路径已验，统一 error 形状正确）；配 key 后应再点一次完整问答/审查/辩论流。
3. **docker-compose v1.29.2 与 qdrant:v1.9.0 兼容问题**（`KeyError: ContainerConfig`）仍在，需用 `docker run` 等价拉起；升级 compose v2 后可消除。
4. **OTel 全链路**今日未开 jaeger 复验（T0.7 阶段已验）；开关常开、jaeger 宕机不阻断业务的语义未变。
5. **代码尚未提交 git**：当前 45 项改动全部在工作区（T0.1–T0.12），等你明确指令再提交。
6. 可选项：根目录 `cuda-repo-wsl-ubuntu-12-6-local_*.deb`（2.9GB）与 `nbody` GPU 样例镜像（456MB）非本项目运行所需，确认后可删。

## 7. 下一阶段（不动，等令）

P1（T1.x）：群组协同会话、轮次锁、worker 接真实 consumer（T1.6）等。**本次到此收口，不自行推进。**
