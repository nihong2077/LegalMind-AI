# LegalMind AI 接口参考

本文档基于仓库代码事实逐端点核实（核实来源：`backend/app/routers/`、`backend/app/core/response.py`、`errors.py`、`security.py`、`frontend/app/lib/`）。
凡标注「已废弃（T4.3）」的端点，仅保留一个版本周期后移除，新代码请改用协同栈端点。

---

## 1. 通用约定

### 1.1 Base URL

后端为 FastAPI 应用，默认监听 `http://localhost:8000`（前端 `API_BASE` 取 `NEXT_PUBLIC_API_URL`，回退本地地址，见 [http.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/http.ts#L14)）。

- 业务接口统一前缀 `/api/*`。
- 健康/运维接口在根路径（`/health`、`/healthz`、`/readyz`、`/metrics`、`/`），**不穿信封**。
- CORS 放开全部来源/方法/头（[main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py#L205-L211)）。

### 1.2 鉴权

- 方式：HTTP `Authorization: Bearer <JWT>`（FastAPI `HTTPBearer`，见 [security.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/security.py#L10)）。
- JWT：`HS256` 签名，密钥 `settings.JWT_SECRET_KEY`；载荷 **`sub` = username**（业务层普遍以 `sub` 作为 `user_id` 收敛数据，如 `get_uid` 返回 `user["sub"]`）。
- 有效期：7 天（`ACCESS_TOKEN_EXPIRE_MINUTES = 60*24*7`）。
- 登录/注册签发 token 后，客户端写入 `localStorage`（键 `legalmind_token:{username}`，按用户名隔离）。
- 例外：协同 SSE 的事件流端点因浏览器 `EventSource` 不支持自定义头，改用 **一次性短票据**（见 §3）。

### 1.3 统一响应信封

成功与失败均为统一信封（[response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py#L43-L72)）：

```jsonc
// 成功
{ "code": 0, "message": "ok", "data": { ... }, "request_id": "req_xxxxxxxxxxxx" }

// 失败
{ "code": 40001, "message": "请求参数错误", "detail": "...", "retryable": false, "request_id": "req_xxxxxxxxxxxx" }
```

- `code == 0` 即成功；非 0 为业务错误码（见 §1.6）。
- `detail` 仅在非空时出现；`retryable` 表示客户端是否宜展示「重试」按钮。
- **信封覆盖范围**：新路由（`EnvelopeRouter`）与 `BizException` 始终穿信封；旧 gateway 路由（`/api/*` 的 JSON 响应）由 `LegacyEnvelopeMiddleware` 把原负载整体下沉到 `data`、HTTP 状态码不变（[response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py#L237-L345)）。**非 `/api/` 路径（健康探针等）不包信封**。

### 1.4 分页约定

- 协同消息：游标分页，`limit`（默认 20，最大 100），游标 `before`（上一页最旧消息 id），响应含 `next_before`。
- 长期记忆：`limit`（默认 20，最大 100）+ `offset`（≥0），响应含 `total/limit/offset`。
- 知识库列表：`page`（≥1）+ `page_size`（1–100）。
- 会话列表：无分页，一次返回全部并带 `total`。

### 1.5 request_id

- 每个响应信封带 `request_id`（`req_` + 12 位 hex）；与响应头 `X-Request-ID` 同源（由 `RequestContextMiddleware` 在最外层绑定 [main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py#L307-L321)）。
- 5xx 信封中 `detail` 会回填该 `request_id` 供后端日志对账，不泄露内部堆栈。

### 1.6 错误码总表

来源于 [errors.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/errors.py#L18-L45)（`ErrorCode` 枚举），SSE `error` 事件复用同一组码：

| code | HTTP | retryable | 默认 message | 说明 |
| --- | --- | --- | --- | --- |
| 0 | 200 | false | ok | 成功 |
| 40001 | 400 | false | 请求参数错误 | 入参校验失败（含旧路由 422 归一） |
| 40004 | 404 | false | 资源不存在 | NOT_FOUND |
| 40009 | 409 | false | 资源冲突 | CONFLICT |
| 40101 | 401 | false | 未登录或登录已失效 | UNAUTHORIZED（也是无效 SSE 票据） |
| 40102 | 401 | false | 登录已过期，请重新登录 | TOKEN_EXPIRED |
| 40301 | 403 | false | 无权访问该资源 | FORBIDDEN |
| 42901 | 429 | **true** | 请求过于频繁，请稍后重试 | RATE_LIMITED |
| 50901 | 409 | **true** | 会商进行中，请稍候再发送 | TURN_LOCK_CONFLICT（同会话轮次锁） |
| 50000 | 500 | false | 服务内部错误 | INTERNAL_ERROR |
| 50201 | 502 | **true** | AI 服务暂不可用，请稍后重试 | LLM_CALL_FAILED |
| 50301 | 503 | **true** | 服务熔断中，请稍后重试 | CIRCUIT_OPEN |
| 50310 | 503 | false | 消息队列不可用，已降级为本地处理 | KAFKA_DEGRADED（仅日志/指标，正常不抛给用户） |
| 50401 | 504 | **true** | 上游服务响应超时，请稍后重试 | UPSTREAM_TIMEOUT |

HTTP 状态 → 业务码的映射见 [response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py#L94-L102) 与 `_STATUS_TO_ERROR`（旧路由）：400/422/405→40001、401→40101、403→40301、404→40004、409→40009、429→42901、500→50000、502→50201、503→50301、504→50401。

### 1.7 SSE 通用

- 传输：`text/event-stream`，`sse-starlette` 的 `EventSourceResponse`，帧以 `\n` 分隔。
- 帧 `id` 为 Redis Stream entry id（形如 `{ms}-{seq}`，严格单调）；客户端按 id 去重实现「断线不丢不重」（[sse.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/sse.ts#L39-L51)）。
- 保活：协同流每 15s 发注释帧 `: ping`（不触发 `onmessage`）。
- 统一 `error` 事件形状（[response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py#L352-L378)）：

```jsonc
{"code": 50201, "message": "AI 服务暂不可用…", "error": "<原始异常>", "detail": "...",
 "retryable": true, "request_id": "req_xxx"}
```

`error` 字段为兼容旧前端保留（值 = `detail` 或 `message`）。

---

## 2. 新协同栈端点

以下路由均基于 `EnvelopeRouter`（统一信封），全部需 `Bearer JWT`。

### 2.1 会话 / 成员 / 消息

来源：[conversations.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/conversations.py)，前缀 `/api/conversations`。除 `POST ""`、`POST /import`、`POST /{id}/messages`、`POST /{id}/forward`、`POST /{id}/minutes`、`POST /{id}/members`、`POST /{id}/turns/{turn_id}/fork` 返回 201 外，其余默认 200。

所有 `/api/conversations/{conversation_id}*` 端点先经 `require_owned_conversation` 依赖：会话不存在 → `40004`，非本人 → `40301`。

#### GET `/api/conversations`
按状态列会话。Query：`status`（可选，仅 `active` / `archived`；非法 → `40001`）。

`data`:
```jsonc
{ "conversations": [ Conversation, ... ], "total": <int> }
```

#### POST `/api/conversations` → 201
创建会话。Body（`CreateConversationRequest`）：

| 字段 | 类型 | 必填/约束 |
| --- | --- | --- |
| `type` | string | 必填，`direct` 或 `group` |
| `case_type` | string | 可选 |
| `template_id` | string | 可选；给了则按案情模板自动铺 roster 与 host（等价于 `case_type`） |
| `title` | string | 可选 |
| `agent_ids` | string[] | 默认 `[]`（群聊模板外追加的 Agent） |
| `my_role` | string | 可选，≤64；**仅 group 有效**，须 ∈ 最终 roster；direct 传了 → `40001` |
| `target_agent_id` | string | 可选，≤64；**仅 direct 必填**，群聊传了 → `40001` |

`data` = 新建的 `Conversation`。错误：`40001`。

#### POST `/api/conversations/import` → 201
把旧 localStorage 会话一次性迁移为服务端 **direct** 历史。**不触发轮次**（逐条按原始时间戳落库 + 热缓存 + SSE 广播）。Body（`ImportConversationRequest`）：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `title` | string | 可选，≤256 |
| `target_agent_id` | string | 可选，≤64；缺省 `general_assistant` |
| `messages` | object[] | 必填非空；≤200 条 |
| `messages[].role` | string | 仅 `user` / `assistant`（默认 `user`） |
| `messages[].content` | string | 非空，≤4000 字 |
| `messages[].ts` | string | 可选 ISO 时间戳；非法/缺失按导入时刻落库 |

`data`: `{ "conversation": Conversation, "imported": <int> }`。错误：`40001`（空/超限/角色非法/内容空或超长/Agent 不存在或停用）。

#### GET `/api/conversations/{conversation_id}`
`data` = `Conversation`（含 `members`）。错误：`40004` / `40301`。

#### PATCH `/api/conversations/{conversation_id}`
Body：`title`（≤256）、`status`（`active` / `archived`），均可选。`data` = 更新后的 `Conversation`。

#### DELETE `/api/conversations/{conversation_id}`
归档会话（`status=archived`）。`data` = 归档后的 `Conversation`，`message="会话已归档"`。

#### POST `/api/conversations/{conversation_id}/members` → 201
追加群成员。Body：`{ "agent_id": "<1–64 字符>" }`。`data` = 新增成员，并广播一条 `system` 通知消息。

#### DELETE `/api/conversations/{conversation_id}/members?agent_id=<id>`
移除成员。Query `agent_id` 必填（缺失 → `40001`）；不在会话中 → `40004`。`data`: `{ "agent_id": "<id>" }`。

#### POST `/api/conversations/{conversation_id}/my_role`
设置/撤销用户扮演角色（跨轮持久化，**仅群聊**）。Body：`{ "my_role": <string|null> }`（≤64；`null`＝不扮演＝交还给 AI）。非群聊或 `my_role` 不在成员中 → `40001`。`data` = 更新后的 `Conversation`。

#### GET `/api/conversations/{conversation_id}/messages`
消息分页。Query：`before`（游标，可选）、`limit`（默认 20，1–100）。首页（无 `before`）命中 Redis 热缓存时 `cached=true`。

`data`:
```jsonc
{ "messages": [ CollabMessage, ... ], "next_before": <string|null>, "cached": <bool> }
```
`CollabMessage`：`id, conversation_id, sender_type, sender_id, sender_name, content, msg_type, round, event_key, fork_parent_message_id, metadata, created_at`（[collab.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/collab.ts#L56-L69)）。

#### POST `/api/conversations/{conversation_id}/messages` → 201 ← 会起轮次
用户发言。Body（`SendMessageRequest`）：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `content` | string | 默认 `""`；仅当 `metadata.hand_back=true` 或 `metadata.conclude=true` 时允许为空 |
| `msg_type` | string | 默认 `text`，仅 `text` / `card` / `minutes` |
| `metadata` | object | 默认 `{}`；`hand_back`、`conclude` 为布尔控制位 |

行为分支（[conversations.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/conversations.py#L478-L553)）：
- **存在未终态轮次**：若为 `running` → `50901`；若为 `interrupted`，本条消息作为「续跑输入」送进挂起轮次（补证 / 接管发言 / `hand_back` 交还 / `conclude` 结束）。
- **无挂起轮次但他人持锁** → `50901`。
- 否则落库用户消息 + 广播 + **创建并执行新轮次**（Kafka 开则入队，降级/关闭则进程内执行）。

`data`（起新轮次或续跑带正文时）:
```jsonc
{ "message": CollabMessage, "event_id": "<stream-id>", "turn_id": "<turn-id>", "status": "running|<其他终态>" }
```
`hand_back` / `conclude` 续跑分支不含新消息：`message=null, event_id=null`，`status` 为轮次终态。

错误：`40001`（内容空、`conclude` 但无进行中会商、参数非法）、`50901`。

#### POST `/api/conversations/{conversation_id}/forward` → 201 ← 不触发轮次
把搜索结果作为「上下文卡片」转发进会话（`msg_type="card"`，`metadata.forwarded=true`）。**不触发轮次**，仅落库 + 热缓存 + SSE 广播，进入后续轮次共享上下文窗。Body（`ForwardMessageRequest`）：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `card_type` | string | 默认 `reference`，≤64 |
| `citations` | object[] | 默认 `[]`，≤20；形状对齐前端引用卡（`source/title/url/content/score`） |
| `content` | string | 默认 `""`，≤4000；与 `citations` 不可同时为空（→ `40001`） |

`data`: `{ "message": CollabMessage, "event_id": "<stream-id>", "turn_id": null, "status": "forwarded" }`。

#### POST `/api/conversations/{conversation_id}/minutes` → 201
手动生成《会商纪要》：汇总本会话各方观点，token 级流式产出并落库（`msg_type="minutes"`）。无参。`data`:

```jsonc
{ "message": CollabMessage|null, "event_id": <string|null>, "reused": <bool> }
```
`reused=true` 表示同轮次已有纪要直接复用未重新生成。错误：`40001`（暂无可整理的会商记录）。

#### GET `/api/conversations/{conversation_id}/turns/{turn_id}/checkpoints`
列某轮次 checkpoint 时间线。`data`:
```jsonc
{ "turn_id": "<id>", "status": "<轮次状态>", "checkpoints": [ CheckpointItem, ... ] }
```
`CheckpointItem`：`checkpoint_id, step, round, directive, reason, force_stop_reason, spoken, next, created_at, is_latest`（[collab.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/collab.ts#L232-L243)）。错误：`40004`（轮次不存在或不属于该会话）。

#### POST `/api/conversations/{conversation_id}/turns/{turn_id}/fork` → 201
从指定 checkpoint 分叉重跑该轮次。Body：`checkpoint_id`（必填，≥1）、`update`（可选，叠加的事实修正）。`data`: `{ "turn_id": "<新轮次id>", "status": "<状态>" }`。错误：`40001`（无法分叉）、`40004`。

### 2.2 SSE 短票据 / 事件流

来源：[collab.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/collab.py)，前缀 `/api/collab/conversations`。

#### POST `/api/collab/conversations/{conversation_id}/events/ticket`
换取 60s 有效、一次性消费的 SSE 短票据。需 JWT + 会话归属。`data`: `{ "events_token": "<token>", "expires_in": 60 }`。错误：`40004` / `40301`。

#### GET `/api/collab/conversations/{conversation_id}/events`（SSE）
详见 §3。

### 2.3 Agent 注册表 / 案情模板

来源：[agents.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/agents.py)，前缀 `/api/agents`。只读、无副作用，仅要求登录。

#### GET `/api/agents/templates`
`data`: `{ "templates": [TemplateCard, ...], "total": <int> }`。每个模板附带 `roster_summary`（`agent_id/name/role_label/is_tool/stage/order`）。

#### GET `/api/agents`
Query：`is_tool`（可选 bool）、`q`（可选，≤64）。`data`: `{ "agents": [AgentInfo, ...], "total": <int> }`。

`AgentInfo`：`agent_id, name, avatar, role_label, description, skill_ref, persona, model_pref, is_tool, sort_order, enabled`（[collab.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/collab.ts#L12-L24)）。

#### GET `/api/agents/{agent_id}`
`data` = `AgentInfo`。错误：`40004`（Agent 不存在）。

> 注意：静态段 `/templates` 先于 `/{agent_id}` 注册，避免被路径参数吞掉。

### 2.4 长期记忆

来源：[memory.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/memory.py)，前缀 `/api/memories`。以 JWT `sub`（username）为 `user_id` 严格隔离。`scope` ∈ `user`/`case`；`status` ∈ `active`/`archived`；`limit` 默认 20 / 最大 100。

#### GET `/api/memories/setting`
`data`: `{ "enabled": <bool> }`（记忆召回总开关）。

#### PUT `/api/memories/setting`
Body：`{ "enabled": <bool> }`（必填）。`data`: `{ "enabled": <bool> }`。

#### GET `/api/memories`
Query：`scope`、`memory_type`、`case_id`、`status`、`starred`（bool）、`q`、`limit`（1–100，默认 20）、`offset`（≥0，默认 0）。`scope`/`status` 非法 → `40001`。`data`:
```jsonc
{ "memories": [MemoryRecord, ...], "total": <int>, "limit": <int>, "offset": <int> }
```

#### POST `/api/memories` → 201
Body（`CreateMemoryRequest`）：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `scope` | string | 默认 `user`，仅 `user`/`case` |
| `memory_type` | string | 必填，1–32 |
| `content` | string | 必填，≥1 |
| `summary` | string | 可选 |
| `importance` | int | 默认 3，1–5 |
| `case_id` | string | 可选 |
| `source_conversation_id` | string | 可选 |
| `source_message_id` | string | 可选 |
| `starred` | bool | 默认 `false` |

`data` = `MemoryRecord`。`MemoryRecord`：`id, user_id, scope, case_id, memory_type, content, summary, importance, source_conversation_id, source_message_id, status, starred, embedding_status, created_at, updated_at`（[memory.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/memory.ts#L13-L30)）。

#### GET `/api/memories/{memory_id}`
`data` = `MemoryRecord`。错误：`40004`。

#### PATCH `/api/memories/{memory_id}`
Body（`UpdateMemoryRequest`，全字段可选）：`content`（≥1）、`summary`、`importance`（1–5）、`memory_type`（1–32）、`status`（`active`/`archived`）、`starred`（bool）。`data` = 更新后的 `MemoryRecord`。错误：`40004`（记忆不存在）。

#### DELETE `/api/memories/{memory_id}`
`data`: `{ "id": "<memory_id>" }`。错误：`40004`。

### 2.5 统一搜索

来源：[search.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/search.py)，前缀 `/api/search`。

#### POST `/api/search/unified`
单框并行四路召回（`law` 法规 / `judge` 类案 / `memory` 我的记忆 / `messages` 会话记录），**失败隔离（fail-open）**：任一路超时/异常只置空该路并写入 `errors`，不抛 500。Body（`UnifiedSearchRequest`）：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `query` | string | 必填，1–500（去空格后为空 → `40001`） |
| `top_k` | int | 默认 5，1–20 |
| `message_limit` | int | 默认 10，1–50 |
| `use_hyde` | bool | 默认 `true` |
| `case_id` | string | 可选 |
| `sources` | string[] | 可选；含未知来源 → `40001`；空=四路全查 |

`data`:
```jsonc
{
  "query": "<string>",
  "results": { "law": [...], "judge": [...], "memory": [...], "messages": [...] },
  "counts": { "law": n, "judge": n, "memory": n, "messages": n, "total": n },
  "errors": { "<source>": "<错误信息>" },
  "took_ms": { "<source>": <int> }
}
```
每路结果归一化形状见 [search.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/search.ts#L17-L49)（`KnowledgeResult` / `MemoryResult` / `MessageResult`，均带 `type` 字段区分）。

---

## 3. SSE 端点详解（协同 v2）

### 3.1 短票据获取

`POST /api/collab/conversations/{id}/events/ticket`（Bearer JWT）→ `data.events_token`（60s、一次性）。票据由 Redis 签发/消费（[collab.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/collab.py#L44-L51)）。

### 3.2 事件流

`GET /api/collab/conversations/{id}/events`

| 参数 | 位置 | 说明 |
| --- | --- | --- |
| `events_token` | Query（**必填**） | `POST .../ticket` 换取的短票据 |
| `last_id` | Query（可选） | 上次收到的 Stream 事件 ID |
| `Last-Event-ID` | Header（可选） | 浏览器重连自动回传 |

服务端行为：
1. 一次性消费票据，无效/过期/已用/会话不匹配 → `40101`（HTTP 401，EventSource 需先重新换票再重连）。
2. 恢复游标 = `last_id` 或 `Last-Event-ID` 或 `"0"`。
3. 先按游标从 Redis Stream 回放缺口（单批上限 500 条），再订阅 Pub/Sub 实时桥接；每帧 `id` = Stream entry id。
4. 每 15s 发注释帧 `: ping` 保活；库内置 ping 已关闭（`ping=3600`）。
5. 流中异常以 `error` 事件送达（`code=50000`, `retryable=true`）。

### 3.3 事件类型与 `data` 形状

后端广播的实际事件类型（[runner.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/runner.py#L61-L65)、[agent_nodes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/agent_nodes.py#L45-L48)、[tool_nodes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/tool_nodes.py#L43-L53)、[minutes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/minutes.py#L36-L38)、[memory_recall.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/memory_recall.py#L26-L29)）：

| 事件 | 触发时机 | `data` 形状 |
| --- | --- | --- |
| `message_start` | Agent 开始发言 / 纪要开始 | `{message_id, event_key, round, sender:{type,id,name}, type:"text"\|"minutes"}` |
| `message_delta` | 每个 token 分片 | `{message_id, delta}` |
| `message_end` | 发言定稿落库 | `{message_id, event_key, round, sender, content, metadata}` |
| `status` | 阶段提示 | `{phase, message, turn_id?, recovered?, round?}`（如 `phase="turn_running"` / `phase="minutes"`） |
| `interaction_required` | 轮次中断待恢复（ask_user / 接管） | `{turn_id, ...中断 payload}` |
| `done` | 轮次成功结束 | `{turn_id, status:"completed"}` |
| `error` | 轮次失败 / 订阅异常 | `{code, message, retryable, request_id, turn_id?}`（或订阅异常 `{code:50000, message, error, retryable}`） |
| `message` | 完整消息落库广播（用户消息 / Agent 卡 / 分隔条 / 通知 / 导入） | 完整消息记录（见下） |
| `tool` | 工具（检索/联网）状态 | `{agent_id, agent_name, tool, status:"running"\|"done"\|"error", query, result_count?, elapsed_ms?, turn_id, round}` |

`message` 事件的 `data` 由不同生产者广播：会话侧（[conversations.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/conversations.py#L176-L191)）广播归一化子集 `{id, sender:{type,id,name}, content, msg_type, round, created_at, metadata}`；Agent/工具/纪要/分隔条侧直接广播落库记录（含 `conversation_id, sender_type, sender_id, sender_name, event_key` 等）。前端渲染以 `sender`/`content`/`msg_type`/`metadata` 为主。

> 核实发现：前端当前订阅的事件名清单（[sse.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/sse.ts#L22-L31)）为 `message_start / message_delta / message_end / status / interaction_required / message / done / error`，**未包含服务端的 `tool` 事件**——即工具状态帧当前不会被该客户端 `onFrame` 收到（非本任务范围内，仅记录事实）。

### 3.4 断线回放

- 各帧 `id` 写入 Redis Stream（`MAXLEN` 容量上限），客户端按 `last_id`/`Last-Event-ID` 续传。
- 前端自实现重连（票据一次性，无法复用旧 URL）：退避 0.5s→1s→2s…上限 8s，最多 12 次（累计 ≈71s），超限才回调 `onError({retryable:true})`（[sse.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/sse.ts#L98-L150)）。

---

## 4. 旧 gateway 端点

来源：[gateway.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/gateway.py)，前缀 `/api`。响应经 `LegacyEnvelopeMiddleware` 统一穿信封（原负载下沉到 `data`）。标 ★ 者为 **已废弃（T4.3）**。

### 4.1 认证与任务

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | 注册（PBKDF2 哈希，Redis 存用户）；成功后直接签发 token | `{access_token, token_type:"bearer", username}`；`40001`(400) |
| POST | `/api/auth/token` | 登录 | `{access_token, token_type, username}`；401 |
| POST | `/api/tasks` | 建任务（Query：`task_type`、Body：`payload`） | `{task_id, status:"pending"}`；限流 429 |
| GET | `/api/tasks/{task_id}` | 查任务状态 | 状态数据；`404` |
| GET | `/api/stream/{task_id}` | 任务进度 SSE（`Last-Event-ID`）；事件 `message`/`ping`/`error` | — |

### 4.2 熔断器与模型

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| GET | `/api/circuit-breaker/{name}` | 熔断器状态 | `{name, state, failure_count, last_failure_time, half_open_success}` |
| POST | `/api/circuit-breaker/{name}/reset` | 重置熔断器 | `{name, state, message}` |
| GET | `/api/models` | 可选模型列表 | `{models:[{id,name,available,status?,error?}]}` |

### 4.3 单聊（★ 已废弃 T4.3）

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| POST | ★ `/api/chat/stream` | 旧单聊 SSE（事件 `status`/`message`/`done`/`error`）；新链路：`/api/conversations` + `/api/conversations/{id}/messages` | SSE |
| POST | ★ `/api/chat` | 旧单聊非流式；呼 LLM，失败 502 | LLM 原始结果；502 |

Body（`ChatRequest`）：`messages`（必填）、`model`（默认 `deepseek-flash`）、`temperature`（0.7）、`max_tokens`（2048）。

### 4.4 仪表盘 / 文档

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| GET | `/api/dashboard/stats` | 统计 | `{chat_count, doc_count, knowledge_count, efficiency_gain}` |
| POST | `/api/dashboard/stats/increment` | Query `key`（`chat_count`/`doc_count`）；非法键 400 | `{status:"ok", key}` |
| GET | `/api/dashboard/cases` | 最近案件（Redis 列表，最多 10） | `CaseItem[]` |
| POST | `/api/dashboard/cases` | Query `title`、`description` | `CaseItem` |
| POST | `/api/documents/upload` | multipart `file`；扩展名白名单、≤10MB、文件名非空 | 文档信息 `{id,name,size,type,status,uploaded_at}`；`40001`(400) |
| GET | `/api/documents` | 文档列表（不含 `path`） | 文档信息数组 |
| GET | `/api/documents/{doc_id}` | 文档详情 | 文档信息；`404` |
| GET | `/api/documents/{doc_id}/content` | 提取正文（txt/图片 OCR/pdf/docx），截断 5 万字 | `{doc_id, name, content}`；`404` |
| POST | `/api/documents/{doc_id}/analyze` | 触发异步分析（Kafka 或 Redis 队列） | `{task_id, doc_id, status:"analyzing"}`；`404` |

### 4.5 多智能体（★ 已废弃 T4.3）

Body（`AgentRequest`）：`query`（必填）、`context`（默认 `""`）、`task_type`（默认 `analyze`）。

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| POST | ★ `/api/agents/run` | 旧串行编排；新链路：collab 主机调度 | `{result, task_type}` |
| POST | ★ `/api/agents/stream` | 旧流式编排（事件 `analysis`/`review`/`research`/`done`/`error`） | SSE |

### 4.6 知识库（仍在使用）

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| POST | `/api/knowledge/search` | Body：`query`、`domain`（默认 `law`）、`top_k`（默认 8）、`use_hyde`（默认 `true`） | `{results, total}` |
| GET | `/api/knowledge/list` | Query：`domain`（`law`/`judge`/`lawyer`，非法 400）、`category`、`keyword`、`page`（≥1）、`page_size`（1–100） | `{items, total, page, page_size}` |

### 4.7 庭审推演（★ 已废弃 T4.3）

Body（`DebateRequest`）：`case_description`（必填）、`evidence_summary`（默认 `""`）、`task_type`（默认 `debate`）、`evidence_supplemented`（默认 false）。新链路：模拟庭审群模板（`/api/conversations` + `case_type=court`）。

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| POST | ★ `/api/debate/run` | 旧庭审推演非流式 | `{result, verdict, judgment_report, plain_language, convergence_reason, kfe, evidence_sufficient, interrupt_reason}` |
| POST | ★ `/api/debate/stream` | 旧庭审 SSE（事件 `metadata`/`message`/`done`/`error`） | SSE |
| POST | ★ `/api/debate/kfe` | 旧 KFE 提取 | `{kfe, evidence_sufficient, interrupt_reason}` |

### 4.8 合同审查（仍在使用）

Body（`ContractReviewRequest`）：`contract_text`（必填）、`user_position`（默认 `乙方`）、`review_stance`（默认 `常规`）。

| 方法 | 路径 | 说明 | `data` |
| --- | --- | --- | --- |
| POST | `/api/contract/review` | 非流式审查 | `{summary, report, classification, risks}` |
| POST | `/api/contract/review/stream` | 流式审查（事件 `metadata`/`message`/`done`/`error`） | SSE |
| POST | `/api/contract/draft-clause` | Body 为 `dict`（`clause_type`/`context`/`user_position`） | `{clause}` |

---

## 5. 健康与运维端点

来源：[main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py#L227-L304)。这些均在**根路径**（非 `/api/`），**不穿信封**。

| 方法 | 路径 | 说明 | 响应 |
| --- | --- | --- | --- |
| GET | `/` | 根信息 | `{message, version}` |
| GET | `/health` | 综合健康：Redis / LLM / PG（多库）/ Qdrant / 内存 | `{status:"healthy"\|"degraded"\|"unhealthy", version, redis, litellm, postgres, qdrant, memory}` |
| GET | `/healthz` | **存活探针**：进程在即 200，**不查任何依赖** | `{status:"ok"}` |
| GET | `/readyz` | **就绪探针**：Redis/PG/Qdrant 健康 + Kafka 已连（或开关关闭）才 200，否则 503 | `readiness_report()` → `{ready, checks:{redis, postgres, qdrant, kafka}}`（[health.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/health.py#L90-L104)） |
| GET | `/metrics` | Prometheus 指标（`text/plain`） | 指标文本 |

---

## 附录：请求会触发 / 不触发轮次的差异（重要）

| 端点 | 是否起轮次 | 落库 + 热缓存 + SSE 广播 |
| --- | --- | --- |
| `POST /api/conversations/{id}/messages` | **是**（起新轮次；有挂起轮次则续跑） | 是 |
| `POST /api/conversations/{id}/forward` | **否**（仅上下文卡片） | 是 |
| `POST /api/conversations/import` | **否**（历史迁移） | 是 |
| `POST /api/conversations/{id}/minutes` | 否（独立纪要产出流程） | 是 |
