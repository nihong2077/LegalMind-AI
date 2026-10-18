# LegalMind AI 微信式协同 UI 改版 + 高并发架构 + Harness 工程实施计划

> 编制日期：2026-10-15
> 范围：AI 对话、多智能体协同、长期记忆、案情搜索、高并发底座（Redis/Kafka/Worker）、可观测性与工程韧性（Harness）
> 不变范围：**合同审查模块（前端页面 + 后端工作流）行为保持不变**

---

## 1. 现状盘点（基于代码核实）

| 维度 | 现状 | 差距 |
|------|------|------|
| 前端 IA | 六个平铺页面：`/chat` `/court` `/documents` `/knowledge` `/cases` `/dashboard`，200px 侧边栏 | 无"单聊/群聊"统一概念，多智能体（模拟法庭）是固定庭审流程而非自由群聊 |
| 会话持久化 | 全部存浏览器 localStorage（`legalmind_sessions` 等 4 个 key），上限 50 条 | 换设备丢失、无法服务端检索、无群组成员模型 |
| 多智能体 | 后端已有 9 个 Skill（法官/原告/被告/调解/书记员/法务分析/合同/法规检索等），`debate_workflow` 15 节点固定编排 | 无 Agent 注册表、无"按案情组队"、无开放群聊编排 |
| 记忆 | 无长期记忆；Qdrant 三套 Collection 存的是法律知识库，与用户无关 | 需新增 Codex 式用户记忆（自动抽取、向量召回、可管理） |
| 案情搜索 | `/knowledge/search` 四级 RAG 检索可用；`/knowledge` 页面偏知识库浏览 | 缺少"法规+类案+记忆+会话"统一搜索与结果转发 |
| SSE | `sse-starlette` + 前端通用解析器；事件 status/message/metadata/done/error；无断线续传 | 群聊需要更丰富的事件（typing/tool/agent 维度）与 Last-Event-ID 重连 |
| 高并发 | 已有 Redis 滑动窗口限流、Redis 熔断器、LLM 缓存；Redis 任务队列**有原语但无 worker 消费进程** | 无消息总线、长耗时 LLM 编排占用请求连接、无水平扩展能力 |
| 可观测性 | 仅 2 个 Prometheus 指标 + 全局异常映射；裸 `logging`；无 request-id；外部调用无重试；返回结构不统一 | 缺结构化日志、链路追踪、重试/超时/降级规范、监控看板、就绪探针 |
| 基础设施 | compose 7 服务（redis/pg/qdrant/litellm×2/fastapi/frontend） | 无 Kafka、无 worker、无 Prometheus/Grafana |

---

## 2. 目标与设计原则

1. **微信式信息架构**：窄导航栏 + 列表栏 + 内容栏；单聊与群聊统一为"消息"，建群即"选案情 → 自动拉 Agent → 可增删"。
2. **编排逻辑贴合用户设想**：用户选案情类型 → 系统按模板自动建群并拉入适配 Agent → 用户可手动追加/移除 Agent → 群聊式多轮发言，SSE 全程透明展示每个 Agent 在做什么。
3. **长期记忆 Codex 化**：服务端自动抽取、向量库存档、跨会话自动召回注入，前端独立模块分类管理（可增删改查）。
4. **高并发适度引入**：不拆微服务、不引入重型流处理。Kafka 只承担"长任务异步化 + 削峰"，Redis 承担缓存/事件桥接/锁；**全部异步链路带进程内降级开关**，本地开发可不启 Kafka。
5. **Harness 工程化**：统一返回结构、统一错误码、可配置重试/超时/熔断/降级、request-id 全链路、结构化日志、指标与看板、可测试。
6. **平滑迁移**：旧端点与合同审查不受影响；localStorage 数据提供一次性迁移脚本。

---

## 3. 总体架构（目标态）

```
┌──────────────────────────────────────────────────────────────┐
│ 浏览器  Next.js 微信式三栏 UI                                  │
│ 消息(单聊/群聊) │ Agent通讯录 │ 案情搜索 │ 记忆 │ 合同审查(不动) │
│ SSE: EventSource + Last-Event-ID 断线续传；http 客户端重试     │
└───────────────┬──────────────────────────────────────────────┘
                │ JWT · JSON / multipart / SSE(GET)
┌───────────────▼──────────────────────────────────────────────┐
│ FastAPI（无状态可多副本）                                      │
│ 中间件: request-id │ 结构化日志 │ 统一响应 │ 限流 │ 指标/追踪   │
│ routers: conversations / collab / agents / memory / search /  │
│          contract(不动) / debate / auth / dashboard           │
│ core: resilience(重试/超时/降级) │ events(Kafka,可降级)        │
│       │ response(统一信封) │ logging(structlog)               │
└───┬───────────────┬───────────────┬───────────────┬─────────┘
    │ 生产任务       │ 缓存/锁/事件桥  │ 持久化         │ 向量
┌───▼────┐   ┌──────▼──────┐  ┌─────▼──────┐  ┌─────▼─────────┐
│ Kafka  │   │ Redis       │  │ PG16       │  │ Qdrant        │
│(KRaft  │   │ 热会话缓存   │  │ 三知识库库  │  │ 三套知识库     │
│单节点) │   │ Pub/Sub     │  │ +app库(新) │  │ +user_memories│
│3 topics│   │ Stream回放  │  │ 会话/群/记忆 │  │ (新Collection)│
└───┬────┘   │ 限流/熔断/锁 │  └────────────┘  └───────────────┘
    │        └─────────────┘
┌───▼────────────────────────────────────┐
│ Workers（独立进程，可水平扩副本）        │
│ collab-worker：多Agent编排 → 事件回推    │
│ memory-worker：记忆抽取/去重/向量化      │
│ doc-worker：OCR/文档分析（兼容旧队列）   │
│ 自身 /healthz + /metrics(:8001)+心跳    │
└────────────────────────────────────────┘
        外部：DeepSeek / LiteLLM / 本地模型 / PaddleOCR（经 resilience 层调用）

可观测性（docker compose profile，按需启动）：
Prometheus ── Grafana（预置看板）；可选 Jaeger(OTLP)；日志 JSON 到 stdout
```

**关键链路（群聊一轮发言）**：

```
用户发消息 POST /api/collab/conversations/{id}/messages
  → 落 PG messages（用户消息）+ 清 Redis 缓存
  → 分布式锁 SET NX lock:conv:{id}（防同群并发轮次）
  → 生产 Kafka topic collab-turns（headers 带 request_id/user_id/turn_id）
  → 立即返回 {turn_id}

前端 EventSource GET /api/collab/conversations/{id}/events?last_id=...
  → 先 XREAD Redis Stream 回放缺口
  → 再 SUBSCRIBE conv:{id}:events 实时转发（ping 15s）

collab-worker 消费 → 记忆召回 → RAG → 按 roster 调度 Agent 串行发言
  → 每一步 XADD Stream（MAXLEN 500）+ PUBLISH Pub/Sub
  → 结束发 memory-events → 解锁
Kafka 关闭时（ENABLE_KAFKA=false）：API 进程内直接运行编排器，事件走 asyncio 桥接，链路行为对前端一致
```

---

## 4. 前端改版设计（微信式）

### 4.1 全局信息架构

桌面端三栏（移动端折叠为单栏 + 返回栈）：

```
┌────┬──────────────┬────────────────────────────┬──────────────┐
│ 64 │   300px      │        flex-1              │  320px(可折叠)│
│ 图 │              │                            │              │
│ 标 │  模块列表栏   │       主内容栏              │  详情/动态栏  │
│ 导 │              │                            │              │
│ 航 │              │                            │              │
└────┴──────────────┴────────────────────────────┴──────────────┘
```

图标导航（自上而下）：

| 图标 | 模块 | 路由 | 说明 |
|------|------|------|------|
| 对话气泡 | **消息** | `/messages/[conversationId]` | 单聊 + 群聊会话列表（类型图标区分） |
| 机器人 | **Agent 通讯录** | `/agents` | Agent 目录、能力介绍、可"拉人进群" |
| 搜索 | **案情搜索** | `/search` | 法规 + 类案 + 记忆 + 历史会话统一搜索 |
| 书签/大脑 | **记忆** | `/memory` | Codex 式长期记忆分类管理 |
| 文档 | **合同审查** | `/documents` | **原样保留**，独立全屏页 |
| 网格 | **工作台** | `/dashboard` | 统计与快捷入口 |

旧路由兼容：`/chat → /messages`（自动确保一个 direct 会话）、`/knowledge → /search`、`/cases → /memory?view=cases`、`/court → /messages?template=court`（P4 收编，见 §11 决策点 D4）。

### 4.2 消息中心（单聊 + 群聊）

**列表栏**：会话项含头像（单聊=AI 头像；群聊=群图标+成员头像叠放）、标题、最后一条消息预览、时间、未读红点、案情类型标签。顶部：新建按钮（下拉：「新建单聊」「发起多 Agent 协同」）。

**建群向导（核心新交互，3 步弹窗）**：

1. **选案情类型**：卡片网格——合同纠纷 / 劳动争议 / 婚姻家事 / 侵权纠纷 / 债权债务 / 房产纠纷 / 模拟庭审 / 自定义（带图标与一句话说明）。
2. **确认 Agent 成员**：系统按模板**预勾选**适配 Agent（头像+能力标签），用户可取消、可从通讯录再添加（即"拉人进群"）；可填写案情名称与初始案情描述（可稍后在群里发）。
3. **创建并进入群聊**。

**群聊窗口（类微信群）**：

- 消息气泡：用户右侧；Agent 左侧，带头像、名称、角色小标签（如「法规检索」「中立调解」）。
- **系统状态条（SSE 透明化，重点需求）**：消息流中插入灰色小条与工具卡片：
  - `🧠 正在召回历史记忆…`（status）
  - `🔍 法规检索员 正在检索"竞业限制 经济补偿"`（typing + tool，头像旁呼吸动画）
  - 卡片：`检索到 6 条相关法规 · 耗时 1.2s`，可展开查看（tool done）
  - `⚖️ 原告律师 正在输入…`
- 同一 Agent 连续消息合并头像；每轮协同结束插入分隔条 `—— 本轮会商结束 · 生成纪要 ——`。
- **@ 提问**：输入框 `@某Agent` 可指定单个 Agent 回答（不触发全员轮次）。
- 输入框支持附件（合同/证据，复用现有上传与 OCR）。
- 右栏（可折叠）：群信息（群名/案情类型/成员管理：加人、移除）、本轮「Agent 动态时间线」、检索结果汇集。
- 一轮结束后 Agent 可产出两类富卡片：**法规/类案引用卡**、**会商纪要卡**（各观点汇总，可复制/下载）。

**单聊窗口**：沿用现有 `ChatInterface` 的 RAG 流式体验，重做为与群聊共用的 `ConversationView` 组件（sender 固定为 general_assistant），模型切换、快捷问题保留。

### 4.3 记忆模块（独立页 `/memory`）

- 顶部分类 Tab：`全部 / 用户画像 / 案件事实 / 诉求与底线 / 时间节点 / 策略偏好`；左侧按案件（群）二次过滤；支持关键词搜索。
- 每条记忆卡：内容摘要、类型标签、重要性（1–5 星）、来源（点击跳转到产生它的会话位置）、时间、置信度；支持**编辑 / 删除 / 手动新增 / 置顶**。
- 顶部开关：`记忆召回` 总开关（允许用户关闭自动记忆，对应 Codex 的隐私控制）。
- `?view=cases` 时展示"案件视图"：按群聊聚合的案件档案（替代旧 /cases）。

### 4.4 案情搜索 `/search`

- 统一搜索框，tab 过滤：`全部 / 法规 / 类案 / 我的记忆 / 会话记录`；后端并行多路召回（复用四级 RAG + judge_db 类案 + user_memories + PG messages ILIKE）。
- 每条结果可 `转发到…`（弹会话列表，像微信转发一样丢进单聊/群聊作为上下文卡片）、可 `引用并新建协同群`。
- 保留知识库浏览模式（法条分类树）作为次级入口。

### 4.5 前端工程改动

- 新增目录：`components/collab/`（ConversationList、ConversationView、GroupOnboarding、AgentBubble、AgentStatusBar、ToolCard、MinutesCard、GroupInfoPanel）、`components/memory/`、`components/search/`、`app/messages/`、`app/agents/`、`app/search/`、`app/memory/`。
- Store 拆分：`useChatStore` 拆为 `useSessionStore`（会话/消息/群）、`useCollabStreamStore`（SSE 事件状态机）、`useMemoryStore`、`useUIStore`（导航/面板）。
- API 层：新增 `lib/http.ts`（统一 fetch 封装：错误码处理、GET 幂等重试、429 退避、401 处理）、`lib/sse.ts`（EventSource 重连/Last-Event-ID/typed events）；旧 `api.ts` 保留并逐步瘦身。
- 样式延续 Tailwind + Framer Motion，不引入新 UI 框架。

---

## 5. 后端：群组与多智能体协同

### 5.1 Agent 注册表（数据驱动，不再硬编码）

`agent_registry` 表初始化 10 个 Agent，绑定现有 Skill：

| agent_id | 名称 | 绑定 Skill / 能力 |
|---|---|---|
| general_assistant | 法律助手 | 现有 chat RAG 链路（单聊默认） |
| legal_analyst | 法务分析师 | LegalAnalyzer |
| contract_reviewer | 合同顾问 | ContractReviewer / ContractReviewSkill |
| legal_researcher | 法规检索员 | RegulatoryResearcher + 四级 RAG（law 域） |
| case_searcher | 类案检索员 | judge_db / Qdrant judge_knowledge 类案检索 |
| mediator | 调解员 | MediatorSkill |
| plaintiff_lawyer | 原告律师 | PlaintiffSkill |
| defense_lawyer | 被告律师 | DefendantSkill |
| judge | 法官 | JudgeSkill |
| clerk | 书记员 | JudgmentReportSkill（纪要/文书） |

每个 Agent 配置：persona system prompt、发言温度/max_tokens、是否工具型（检索类产出卡片而非长文）、默认排序。

### 5.2 案情模板（case_roster_templates）

| 案情类型 | 自动拉入 Agent |
|---|---|
| 合同纠纷 | 法务分析师、合同顾问、法规检索员、调解员 |
| 劳动争议 | 法务分析师、法规检索员、类案检索员、调解员 |
| 婚姻家事 | 法务分析师、调解员、类案检索员 |
| 侵权纠纷 | 法务分析师、类案检索员、法规检索员 |
| 债权债务 | 法务分析师、法规检索员、合同顾问 |
| 房产纠纷 | 法务分析师、类案检索员、法规检索员 |
| 模拟庭审 | 法官、原告律师、被告律师、书记员（对接现有 debate_workflow） |
| 自定义 | 用户勾选，默认法务分析师 + 法规检索员 |

### 5.3 群聊编排器（collab-worker 内，轻量 LangGraph）

第一版采用**规则调度 + @ 定向**，避免复杂的自由辩论不可控：

```
用户消息入库
 → ① 记忆召回（Qdrant user_memories，top5，按 user_id 过滤）
 → ② 共享上下文准备：案情描述 + 历史消息窗(20条) + RAG 法规/类案（tool 事件可见）
 → ③ 调度判定：
      · 消息含 @agent → 仅该 Agent 发言
      · 否则按群成员顺序串行发言（检索类并行预取，发言串行输出）
      · 每 Agent 看到：persona + 共享上下文 + 前面成员本轮发言（链式观点递进）
 → ④ 每个 Agent：typing → 流式 message（token 级，走 LLM astream）
 → ⑤ 书记员可选生成《会商纪要》（首轮结束后由用户按钮触发，或每 3 轮自动一次）
 → ⑥ 发 memory-events；解锁；round_done
```

庭审模板走专用适配器：复用 `build_debate_workflow`，把节点事件翻译为统一群聊 SSE 事件（node→agent 映射沿用现 court 页 `detectRole` 逻辑），法官的补证中断变成群内一张「待补证卡片」，用户在群里补发证据即重启。

### 5.4 统一 SSE v2 事件协议

所有协同/对话流统一（旧 chat/contract/debate 端点暂不动）：

| event | data 关键字段 | UI 表现 |
|---|---|---|
| `status` | `phase, message, agent_id?` | 灰色状态条 |
| `typing` | `agent_id, agent_name, avatar, role` | 头像呼吸/正在输入 |
| `tool` | `agent_id, tool(rerank_search/case_search/memory_recall/ocr), status(running/done/error), query?, result_count?, elapsed_ms?` | 工具进度卡片 |
| `message` | `id, sender{type,id,name,avatar,role}, content, msg_type(text/card/minutes), round, created_at` | 气泡 |
| `round_done` | `round, minutes?` | 轮次分隔条 |
| `done` | `turn_id, status(completed/interrupted)` | 结束 |
| `error` | `code, message, retryable, request_id` | 错误条 + 重试按钮 |

SSE 端点为 `GET`（原生 EventSource 支持自动重连与 `Last-Event-ID`）；鉴权用一次性短票据：进群时 `POST /api/collab/conversations/{id}/events/ticket` 换取 60s 有效的 `events_token`（存 Redis，绑定 user+conversation），EventSource 以 query 携带，避免 JWT 出现在 URL 长期有效。事件同时 XADD 到 Redis Stream（MAXLEN 500）支撑断线缺口回放。

### 5.5 新增 API（均为 `/api` 前缀，统一响应信封见 §7.1）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/agents` | Agent 目录 |
| GET | `/agents/templates` | 案情类型 → 推荐 roster |
| GET/POST | `/conversations` | 会话列表 / 创建会话（body: type=direct/group, case_type?, title?, agent_ids?）→ 建群时按模板补全员 |
| GET/PATCH/DELETE | `/conversations/{id}` | 详情/改名/归档 |
| POST/DELETE | `/conversations/{id}/members` | 追加 Agent / 移除 Agent |
| GET | `/conversations/{id}/messages?before=` | 历史消息分页（Redis 缓存 + PG） |
| POST | `/conversations/{id}/messages` | 用户发言 → 触发轮次，返回 turn_id |
| GET | `/conversations/{id}/events` | SSE 订阅（query: events_token，Last-Event-ID 头） |
| POST | `/conversations/{id}/events/ticket` | 换 SSE 短票据 |
| POST | `/conversations/{id}/minutes` | 手动生成会商纪要 |
| GET/POST/PATCH/DELETE | `/memories` | 记忆 CRUD（list 支持 type/case_id/q 过滤） |
| POST | `/search/unified` | 法规/类案/记忆/会话统一搜索 |

旧端点全部保留；合同审查相关端点零改动。

---

## 6. 长期记忆设计（Codex 式）

**存储（PG 为权威源，Qdrant 为向量索引）**：

- PG 新库 `legalmind_app`，表 `memories(id, user_id, scope(user/case), case_id?, memory_type, content, summary, importance, source_conversation_id, source_message_id, status(active/archived), embedding_status, created_at, updated_at)`，内容更新时重嵌。
- Qdrant 新 Collection `user_memories`（1024 维/Cosine，与现有 embedding 一致），payload：`memory_id, user_id, scope, case_id, memory_type, importance, status`。

**写入（自动 + 手动）**：

```
一轮对话结束 → Kafka memory-events(turn_id, user_id, conversation_id)
 memory-worker:
   1. 取本轮消息 + 该用户已有记忆摘要
   2. Flash LLM 抽取候选记忆（结构化 JSON：事实/偏好/诉求/时间节点）
   3. 候选与现有记忆向量比对：cosine ≥ 0.90 合并更新，0.75–0.90 标记去重提示，< 0.75 新增
   4. PG upsert → embedding → Qdrant upsert；失败重试 3 次进死信（Kafka DLQ）
```

**召回与注入**：单聊/群聊每轮开始，用用户最新消息 embedding 在 `user_memories` 按 `user_id`（群聊再加 `case_id`）过滤取 top5，作为**独立 system 消息**注入（沿用项目现有"不覆盖系统提示词"约定）；召回过程发 `tool: memory_recall` 事件，前端可见"想起了什么"。用户可在记忆页删除单条或关闭总开关（关闭后不写不读）。

**短期记忆/会话历史**：PG `messages` 持久化替代 localStorage；Redis 缓存最近 20 条/会话；上下文窗口仍取最近 20 条（与现逻辑一致）。

---

## 7. Harness 工程：调用规范与可观测性

### 7.1 统一返回结构与错误码

新路由全部采用信封；旧路由不动（P4 评估迁移）：

```json
// 成功
{ "code": 0, "message": "ok", "data": { }, "request_id": "req_xxx" }
// 失败
{ "code": 41001, "message": "AI 服务暂不可用，已自动重试 3 次", "detail": "...", "request_id": "req_xxx" }
```

错误码段位：`0` 成功；`40xxx` 入参/认证（40101 未认证、40102 token 过期、42901 限流）；`50xxx` 服务端（50201 LLM 调用失败、50301 熔断中、50401 超时、50310 Kafka 不可用已降级）；`retryable=true` 的前端给"重试"按钮。SSE `error` 事件携带同样字段。

### 7.2 resilience 层（新增 `backend/app/core/resilience.py`）

- **重试 tenacity**（异步）：指数退避 0.5s→1s→2s + 随机抖动；默认 3 次；仅对 429/502/503/504/连接错误/超时重试；POST 非幂等不重试，流式响应**首字节前**可重试、首字节后不重试；带总预算（jitter deadline 30s）。
- **超时分层**：connect 5s、普通读 30s、LLM 流式读 120s、OCR 沿用 300s（均可配置）。
- **熔断**：保留并复用现有 `RedisCircuitBreaker`，统一从 resilience 入口调用，按服务名隔离（llm_deepseek / litellm / local_model / ocr / qdrant）。
- **降级链文档化**：本地微调模型 → deepseek-flash（已有，保留）；RAG 失败 → 纯 LLM（已有）；Kafka 不可用 → 进程内编排；Qdrant 不可用 → PG 关键词；全失败 → 明确错误码而非 500。
- 每次重试/熔断/降级产生结构化日志与 Prometheus 计数。
- 先落到 `llm_client`、`ocr_service` 两个外部调用点，后续新 worker 全部复用。

### 7.3 结构化日志与链路 ID

- 引入 `structlog`，JSON 输出到 stdout（compose 可直接采集）。
- 中间件生成/透传 `X-Request-ID`，经 `contextvar` 贯穿；日志字段：`request_id, user_id, method, route, status, latency_ms, retry_count, agent_id, turn_id, case_type`。
- 跨进程：API → Kafka headers（request_id/turn_id）→ worker 日志同 ID；Redis 事件 payload 携带 request_id。前端控制台与错误提示也显示 request_id 短码，便于报障。

### 7.4 指标 / 追踪 / 探针 / 看板

- 扩充 Prometheus 指标：`http_requests_total/duration`（补全标签）、`llm_calls_total{model,status}`、`llm_duration_seconds`、`retry_total{service,attempt}`、`circuit_breaker_state`、`collab_turns_total{case_type,status}`、`agent_invocations_total{agent,status}`、`memory_*`、`kafka_consumer_lag`、`worker_heartbeat`。
- OpenTelemetry：FastAPI/httpx 自动埋点，OTLP exporter 默认关闭，设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 后启用；不引入则靠 request_id 串日志。
- 健康检查拆分：`/healthz`（存活，不查依赖）与 `/readyz`（Redis/PG/Qdrant/Kafka 生产者可用）；worker 同类探针 + 每 10s 写 Redis 心跳 key（TTL 30s）。
- `docker-compose.yml` 新增 `profiles: [observability]`：Prometheus（抓取 fastapi:8000、worker:8001）+ Grafana，预置一个看板 JSON（QPS/P50/P95/错误率/重试/熔断状态/Kafka lag/worker 心跳）。Jaeger all-in-one 同 profile 可选。

### 7.5 测试 Harness

- `backend/tests/` 新增：`test_resilience.py`（重试次数/熔断状态机/降级开关）、`test_collab_orchestrator.py`（mock LLM 的 roster 调度、@ 定向、加人移除）、`test_memory_service.py`（抽取去重阈值、召回过滤）、`test_api_conversations.py`（信封结构/权限/分页）、`test_events.py`（Stream 回放与 Last-ID）。
- Worker 编排测试以 fake producer + fake LLM 完成，不依赖真实 Kafka。

---

## 8. 高并发底座：Kafka / Redis / Worker（适度设计）

### 8.1 Kafka（KRaft 单节点，无 Zookeeper）

- 镜像 `bitnami/kafka:3.7`（备选 redpanda 单容器，API 兼容、更省资源，作为决策点 D1）；compose 新增服务，持久化卷；Topic 仅 3 个，partition=3：

| Topic | 生产者 | 消费者 | 用途 |
|---|---|---|---|
| `collab-turns` | fastapi | collab-worker（group，可多副本） | 群聊/单聊长耗时编排削峰 |
| `memory-events` | collab-worker / fastapi | memory-worker | 记忆抽取与向量化 |
| `doc-tasks` | fastapi | doc-worker | OCR/文档分析（替换现有无消费者的 List 队列） |

- 死信：消费失败重试 3 次后进 `*-dlq`（不引入 connector，worker 内实现），失败可查可重放。
- 客户端 `aiokafka`；封装在 `core/events.py`：启动时懒连接、发送失败不阻断主流程（降级 + 50310 日志）。
- 开关 `ENABLE_KAFKA=true/false`：false 时 collab 在 API 进程内执行（直接同 SSE generator，等价现 debate/stream 模式），memory/doc 走 `asyncio.create_task` + 启动期积压清扫。**本地开发默认 false，compose 默认 true。**

### 8.2 Redis 用途增量（不动现有 key）

| 新增用途 | Key/结构 |
|---|---|
| 会话消息缓存 | `legalmind:conv:{id}:messages:recent`（List/JSON，TTL 10min） |
| SSE 事件回放 | `legalmind:conv:{id}:events`（Stream，MAXLEN 500） |
| SSE 实时桥接 | Pub/Sub `legalmind:conv:{id}:events` |
| 同群轮次锁 | `legalmind:lock:conv:{id}`（SET NX PX 10min，finally 释放） |
| SSE 短票据 | `legalmind:sse_ticket:{ticket}`（String，TTL 60s） |
| Worker 心跳 | `legalmind:worker:{id}:hb`（TTL 30s） |
| Agent 在线/typing | `legalmind:conv:{id}:typing`（TTL 5s） |

连接池上限由 20 提至 50（可配置），API 与 worker 分客户端库号（db0/db1 逻辑隔离仍同实例，简单优先）。

### 8.3 Worker 进程

新增 `backend/worker/main.py`（同一镜像、不同启动命令，compose `command` 区分）：

- `python -m worker --role collab|memory|doc`；可 `docker compose up --scale worker-collab=2`。
- 内含：Kafka consumer 组、Redis、PG、Qdrant、LLM client 复用 core 层；自身 8001 端口 `/healthz` `/metrics`；优雅停机（处理完当前任务再退出）。
- 现 `/documents/{id}/analyze` 的入队逻辑改为生产 `doc-tasks`（旧 `enqueue_task` 保留兼容）。

---

## 9. 数据模型变更

新建 PG 库 **`legalmind_app`**（`pg_client.py` 扩为四引擎；初始化 SQL `04-app-schema.sql`）：

```sql
conversations(id UUID PK, user_id VARCHAR, type VARCHAR(direct/group),
  case_type VARCHAR, title VARCHAR, status VARCHAR(active/archived),
  created_at, updated_at)
conversation_members(id, conversation_id FK, agent_id VARCHAR, role VARCHAR,
  is_auto BOOL, joined_at)
messages(id UUID PK, conversation_id FK, sender_type VARCHAR(user/agent/system),
  sender_id VARCHAR, sender_name VARCHAR, content TEXT, msg_type VARCHAR,
  round INT DEFAULT 0, metadata JSONB, created_at)  -- 索引(conversation_id, created_at)
agent_registry(agent_id PK, name, avatar, role_label, description, skill_ref,
  persona TEXT, model_pref JSONB, is_tool BOOL, sort_order, enabled BOOL)
case_roster_templates(case_type PK, name, description, agent_ids JSONB)
memories(id UUID PK, user_id, scope, case_id NULL, memory_type, content TEXT,
  summary TEXT, importance SMALLINT, source_conversation_id, source_message_id,
  status VARCHAR, embedding_status VARCHAR, created_at, updated_at)
```

Qdrant：新增 `user_memories` Collection（1024/Cosine），不动现有三套知识库 Collection。

---

## 10. 依赖与配置变更

- `backend/requirements.txt` 新增：`aiokafka>=2.10`、`tenacity>=8.2`、`structlog>=24.1`、`opentelemetry-sdk / opentelemetry-instrumentation-fastapi / httpx`（可选，P3）。
- `config.py` / `.env.example` 新增：`ENABLE_KAFKA`、`KAFKA_BOOTSTRAP_SERVERS`、`APP_DB_URL`、`RETRY_MAX_ATTEMPTS=3`、`LLM_STREAM_TIMEOUT=120`、`MEMORY_SIMILARITY_MERGE=0.90`、`OTEL_EXPORTER_OTLP_ENDPOINT=`（空=关）、worker 并发数等。
- `docker-compose.yml`：新增 `kafka`、`worker-collab`、`worker-memory`、`worker-doc`（同一 backend 镜像）；observability profile 加 `prometheus`、`grafana`（可选 `jaeger`）；fastapi 依赖增加 kafka（`condition: service_started`，不做健康硬依赖以便降级）。
- 新增 `deploy/observability/`：prometheus.yml、grafana provisioning + 预置 dashboard。
- 前端 `package.json` 预计不新增运行时依赖（EventSource 为浏览器原生）。

---

## 11. 分阶段实施计划与决策点

### P0 工程地基（后端为主）
1. `04-app-schema.sql` + 四引擎；resilience 层（tenacity 重试/超时/统一降级入口）并接入 llm_client、ocr_service。
2. structlog + request-id 中间件；统一响应信封 `ApiResponse` + 业务异常基类 + 错误码表。
3. compose 引入 kafka（先跑通生产/消费 hello world）；`core/events.py` 与 ENABLE_KAFKA 降级。
4. `/healthz` `/readyz`；worker 骨架 + 心跳 + 8001 指标。
**验收**：日志为 JSON 且带 request_id；拔网期间 LLM 调用按策略重试并记录 retry 指标；关闭 Kafka 服务仍可正常启动。

### P1 群组协同（前后端主体）
5. Agent 注册表 + 案情模板初始化数据；conversations/members/messages API + Redis 缓存 + 锁。
6. collab 编排器（规则调度 + @ 定向 + 庭审适配器），SSE v2（typing/tool/message/done），Stream 回放 + 短票据。
7. collab-worker Kafka 消费 + 进程内降级双模式。
8. 前端三栏 IA 骨架；消息列表；单聊接入新链路；建群向导；群聊渲染（气泡/状态条/工具卡）；右栏群管理。
**验收**：选择"合同纠纷"自动建群拉入 4 个 Agent 并串行发言；可手动加/移除 Agent；SSE 中能看到记忆召回与检索过程；刷新/换浏览器登录后历史仍在。

### P2 长期记忆
9. memory CRUD API；Qdrant user_memories；memory-worker（抽取/去重/向量化/DLQ）；对话链路召回注入与 tool 事件。
10. 前端记忆页（分类/编辑/删除/手动新增/开关/来源跳转）+ 案件视图。
**验收**：完成两轮回话后记忆页自动出现结构化记忆；新会话能引用旧案事实；删除后不再召回。

### P3 搜索、前端韧性、可观测性收尾
11. `/search/unified` 多路召回；前端搜索页 + 转发到会话/引用建群。
12. 前端 http.ts（401/429/幂等重试）+ sse.ts（Last-Event-ID 自动重连、错误重试按钮）。
13. 指标补齐 + Grafana 看板 + worker lag 面板；OTel 可选接入。
**验收**：worker 重启/网络抖动时群聊 SSE 自动续传不丢消息；看板可看 QPS、P95、重试、熔断、Kafka lag；doc-tasks 走通 OCR 异步链路。

### P4 收编与迁移
14. 决策点 D4：`/court` 收编为"模拟庭审"群模板（推荐，体验统一）或保留独立页仅换导航；旧路由重定向。
15. localStorage → 服务端一次性迁移脚本（登录后弹窗引导，把本地会话导入为 direct 群历史）；旧端点标注 deprecated。
16. 更新 `CODE_WIKI.md`；空的 `docs/architecture.md`、`api-reference.md`、`deployment.md` 借本次落地补齐。

### 需您拍板的决策点

| # | 决策点 | 推荐方案 | 备选 |
|---|---|---|---|
| D1 | 消息队列实现 | bitnami/kafka 3.7 KRaft 单节点（生态标准） | Redpanda 单容器（更省内存，Kafka 协议兼容） |
| D2 | 应用数据表位置 | 新建 `legalmind_app` 库（四引擎，职责清晰） | 塞进现有三库之一（省一个连接，语义混乱） |
| D3 | Agent 发言策略 | 默认按 roster 串行（有群聊递进感、省 token），@ 可定向，检索类并行预取 | 全员并行（快但像答非所问） |
| D4 | 模拟法庭 `/court` | P4 收编为群聊"模拟庭审"模板，补证卡片群内化 | 永久保留独立页 |
| D5 | 旧接口返回结构 | 新接口新信封、旧接口不动（零回归风险） | 全量强改（前端同步大改） |
| D6 | 追踪系统 | 日志 request_id 起步，OTel 留开关，Jaeger 按需 profile 启动 | 一开始就部署全链路追踪 |
| D7 | 默认部署形态 | compose 一条命令含 Kafka+3 worker；ENABLE_KAFKA=false 支持轻量本地开发 | 只提供全量模式 |

---

## 12. 风险与对策

1. **复杂度膨胀**：编排只做规则调度，不做 Agent 自由互辩（自由辩论已有 debate_workflow 承接）；Kafka 仅 3 topic；不引入 Flink/Celery/n8n。
2. **Kafka 成为本地开发负担**：ENABLE_KAFKA 降级 + profile 启动；CI 测试不依赖 Kafka。
3. **SSE 鉴权与重连**：60s 一次性短票据 + Redis Stream 回放，避免 token 进 URL 长期暴露、避免重连丢消息。
4. **记忆抽取噪声/幻觉**：高阈值合并（0.90）、重要性分级、用户可删可关；抽取 prompt 约束"只记录明确陈述的事实/偏好"。
5. **多 worker 下同群并发**：Redis 锁保证同群同时只有一个活跃 turn；锁带 TTL 防死锁。
6. **Token 成本**：群聊每 Agent 仅注入共享上下文窗而非全部历史；检索类 Agent 输出短卡片；纪要按需生成。
7. **回归风险**：合同审查零改动；旧端点全部保留；前端旧组件在新链路验证通过后再下线。

---

## 13. 主要新增/改动文件清单（预览）

**后端新增**：`core/resilience.py`、`core/logging.py`、`core/events.py`、`core/app_db.py`（或并入 pg_client）、`routers/conversations.py`、`routers/collab.py`、`routers/agents.py`、`routers/memory.py`、`routers/search.py`、`services/collab/orchestrator.py`、`services/collab/roster.py`、`services/collab/adapters/{generic,court}.py`、`services/memory/extractor.py`、`services/memory/store.py`、`worker/main.py`、`worker/consumers/{collab,memory,doc}.py`、`sql/init/04-app-schema.sql`、`scripts/migrate_local_storage.py`（配合前端导出）、tests ×6。
**后端改动**：`main.py`（中间件/探针/日志）、`core/config.py`、`core/llm_client.py`、`core/redis_client.py`、`services/ocr_service.py`、`routers/gateway.py`（旧端点兼容 + 文档分析入 Kafka）、`requirements.txt`、`Dockerfile`、根 `docker-compose.yml`。
**前端新增**：`app/messages/`、`app/agents/`、`app/search/`、`app/memory/`、`components/collab/*`、`components/memory/*`、`components/search/*`、`store/useSessionStore.ts` 等 4 个 store、`lib/http.ts`、`lib/sse.ts`。
**前端改动**：`components/Sidebar.tsx`（换图标导航）、`app/layout.tsx`、旧页面重定向；`ChatInterface`/`court`/`knowledge`/`cases` 逻辑迁入新组件；`documents` 页面不动。
