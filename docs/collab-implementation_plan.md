# LegalMind 协同改版 — 汇总实施计划（执行版）

> 日期：2026-10-15
> 依据（三份已定稿规格，均在 [docs/](../)）：
> - [collab-ui-refactor_plan.md](../docs/collab-ui-refactor_plan.md) 总体方案（P0-P4 骨架）
> - [collab-scheduling_spec.md](../docs/collab-scheduling_spec.md) 调度澄清、模板、Harness 细节
> - [collab-supervisor-checkpoint_spec.md](../docs/collab-supervisor-checkpoint_spec.md) 星型图 + Checkpointer 中断/恢复（其"host 用 Command(goto) 调度"写法已由本计划 §1 决策 D14 修订：发言顺序/续轮权移交隐藏「演讲排序智能体」scheduler，主持人仅保留程序性决策与发言）
>
> 冲突时以本计划 §1 优先级为准；本计划把三份规格落成**可执行的任务卡、文件清单、依赖关系与开工顺序**。

---

## 0. 一分钟看懂这次要改什么

| 域 | 改动一句话 | 改/不改 |
|---|---|---|
| 前端信息架构 | 六平铺页 → 微信式「图标栏+会话列表+聊天区+右栏」：消息（单聊/群聊）、Agent 通讯录、案情搜索、记忆、合同审查、工作台 | 大改 |
| 前端交互模型 | 消息中心统一「单聊/群聊」：**单聊可与全部 10 个 Agent 任选其一**；群聊由**主持人 Agent 主导**组队辩论（模板预设/用户增删角色），支持**用户接管扮演**任一角色（轮到暂停 / 可交还 AI）；**SSE 推送保留** | 大改 |
| 多智能体 | 新写**星型图**：**主持人（法官/调解员）只负责发言与程序决策，发言顺序/是否续轮由「隐藏排序智能体」决定**；一人一气泡串行；@ 可定向 | 新建 |
| 模拟法庭 | 作为新图的 court 模板（host=judge）收编；**旧 debate_workflow 与旧端点原样保留一个版本周期** | 新建+保留 |
| 长期记忆 | 新增 user_memories（Qdrant）+ memories 表（PG 新库）；memory-worker 自动抽取/去重/召回 | 新建 |
| 案情搜索 | 法规+类案+记忆+历史会话统一搜索，结果可转发到群/引用建群 | 新建 |
| 高并发 | apache/kafka 3.7 官方镜像 KRaft + 3 个 worker（collab/memory/doc）；Redis Stream/PubSub/锁/票据；ENABLE_KAFKA 可降级单进程 | 新增 |
| Harness | 统一信封/错误码、tenacity 重试、超时分层、熔断复用、request-id、structlog、**OTel+Jaeger 常开**、Prometheus/Grafana、healthz/readyz；**旧 29 个端点一并改造**（含合同审查，行为不变） | 全量横切 |
| 持久化 | 新建 PG `legalmind_app` 库（pg_client 加第四引擎）+ LangGraph PG Checkpointer；会话/消息服务端化，替代 localStorage | 新增 |
| 合同审查 | 前端页面与业务工作流**零功能改动**，仅穿 Harness 横切层（信封/日志/重试/追踪）并做回归 | 不动业务 |

---

## 1. 锁定决策（您已拍板，实施不再反复）

| # | 决策 |
|---|---|
| D1 | Kafka 用 **Apache 官方镜像 `apache/kafka:3.7.2` KRaft**（无 ZK） |
| D2 | 应用表放**独立新库 `legalmind_app`**；三知识库库不动；pg_client 扩为四引擎 |
| D3 | Agent **串行、一人一条独立气泡（换行）**；@ 定向单人；**发言顺序由隐藏排序智能体（scheduler）决定（D14 修订），代码只做护栏** |
| D4 | `/court` **先收编**为 court 群模板；模板表驱动，后续加模板=插数据+（可选）adapter |
| D5 | **旧接口全部纳入 Harness**（统一信封/错误码/日志/重试/追踪），同批次前后端切换，合同审查做回归红线 |
| D6 | **追踪常开**：OTel 默认启用 + Jaeger 进 compose 默认服务；Kafka headers 透传 traceparent |
| D7 | 双模式：compose 全量（Kafka+3 worker+Jaeger）；`ENABLE_KAFKA=false` 单进程轻量本地开发 |
| A1（架构修订）⚠️ | **业务调度权归主持人 LLM**：星型图无业务固定边，host 返回 `Command(goto=)`；代码仅三类护栏（白名单/max_rounds+预算/JSON 校验修复一次）。**（D14 部分修订：发言排序/续轮权移交隐藏 scheduler，主持人仅保留程序性决策与发言）** |
| A2 | **中断恢复用 LangGraph 原生机制**：补证 `interrupt()/resume`；异常按 super-step 从 PG checkpoint 自动续跑；手动回退用 state history fork |
| A3 | 旧 debate_workflow/旧端点**保留不动**；JudgeSkill 加 `collab_mode` 提示词分支，默认 False |
| A4 | 成本：host 的结构化 directive 用 flash，开庭/裁决等关键发言用 pro；普通群 max_rounds=2，court=3；单 turn 上限 20 次调用/60k tokens |
| S1 | **所有 AI 消息一律 token 级流式**（群聊每个 Agent、主持人口语发言、单聊、纪要全部 `astream` 逐 token 推 SSE），禁止整段返回；SSE 采用 `message_start`(分配 message_id/event_key) → 多帧 `message_delta`(增量文本) → `message_end`(定稿落库) 三事件；前端按 message_id **追加合并，严禁整包替换**；主持人流式末尾的 directive JSON 在服务端缓冲剥离（不推给用户），解析失败按护栏 §2.4 处理 |

**前端/交互设计锁定（第二轮澄清，用户已拍板）**

| # | 决策 |
|---|---|
| D8 | 前端 IA 保持**微信式三栏**（图标栏 ｜ 会话列表 ｜ 聊天区 ｜ 可折叠右栏）；**SSE 推送保留**，沿用 T1.1 的短票据 + Redis Stream 回放 + Pub/Sub 桥（不另起通道） |
| D9 | 会话统一分 `direct`/`group`；**单聊可对全部 10 个 Agent 任选其一**（`direct` 会话带 `target_agent_id`），消息/SSE 链路与群聊同构、共用 `ConversationView` |
| D10 | **群聊由主持人 Agent 主导**：庭审模板 host=`judge`，普通会商 host=调解员/法务分析师（按模板）；成员来自模板预设或用户增删；**串行发言、一人一条独立气泡** |
| D11 | **扮演＝接管式，仅群聊**：轮到「用户扮演的那个 Agent」时**暂停等用户输入**（AI 不再代其生成），用户可随时**「交还给 AI」**恢复自动；接管发言以 `sender_type=user` + `metadata.actor_agent_id` 落库，前端标「你（扮演 XX）」 |
| D12 | **建群向导 3 步**（①选案情类型 → ②确认/增减 Agent、并选「我不扮演／我扮演某人」→ ③创建进入）；第二步选择落 `my_role`（空＝不扮演） |
| D13 | 主持人只出**结构化建议**（HostDirective JSON），**最终由系统代码裁决**（越权/超时/超轮次一律走 §2.4 护栏默认）——与 A1 一致 |

**第三轮澄清锁定的架构调整（用户已拍板）**

| # | 决策 |
|---|---|
| D14 | **新增「演讲排序智能体」（scheduler）**：**默认对用户隐藏**——不进 `agent_registry`、不出现在通讯录/建群向导/成员列表、不产生任何气泡；职责**仅限**「决定下一个发言者 + 是否继续下一轮」；**补证 / 裁决 / 结束 仍由法官（主持人）程序决策**。它作为图中的**内部节点**存在（不是用户可见 Agent）。**部分修订 A1**：调度权从主持人 LLM 移交给 scheduler，主持人只保留程序性决策与发言。 |
| D15 | **辩论的中断恢复 / 错误重试特殊规则**（三条，与通用于普通会商/单聊的规则区分）：① **恢复/续跑严格保序不跳人**——resume 或 checkpoint 续跑后从断点继续，未发言者按原序补齐，已发言者不重生成、不重复气泡；② **每次排序决策落审计**——`host_decisions` 记录点了谁、是否续轮、reason，前端时间线可查；③ **排序智能体失败降级兜底**——scheduler 调用失败/超时 → 回退模板默认顺序（或主持人兜底），**不中断整轮**。（**不**采用"裁决节点失败不自动重试"） |
| D16 | **前端刷新状态恢复**归入 **T1.1 补丁**（与 `my_role`/`target_agent_id` 同批、随 T1.2 提交）：页面加载时 验 JWT → `GET /api/conversations` 拉列表 → 恢复当前会话 → 拉消息（命中服务端热缓存）→ 重建 SSE（带 `last_id`）。修复"已登录仍刷新即丢" |

---

**第四轮澄清：前端 IA 收敛（用户拍板，修订 D8–D12 的落地范围）**

| # | 决策 |
|---|---|
| D17 | 前端导航收敛为 **「消息中心」+「合同审查」** 两项；其余入口（智能咨询 `/chat`、模拟法庭 `/court`、法律知识库 `/knowledge`、案件记忆 `/cases`、工作空间 `/dashboard`）**从导航隐藏**，且**直接访问旧 URL 时重定向到 `/messages`**（路由代码保留不删，不新增重定向以外的行为） |
| D18 | **智能咨询＝单聊**：消息中心内「+」选 1 个 Agent → `direct` 会话（`target_agent_id`），复用旧智能咨询的 RAG 问答能力，但统一走 collab 消息/SSE 链路 |
| D19 | **模拟法庭＝群聊**：消息中心内「+」选案情模板 → `group` 会话；主持人（court=judge）主导，用户可扮演任一成员或不扮演（`my_role`）。**实时体感（流式气泡／辩论相位／补证卡片／判决卡）保留，但统一走新 collab SSE（`/api/collab/conversations/{id}/events`），不复用旧 `/debate/stream` 端点** |

---

## 2. 实施起点（已核实的代码事实）

- Python：本地 venv **3.12**；[backend/Dockerfile](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/Dockerfile) 现在是 `python:3.10-slim` → **需升 3.12 对齐**。
- LangGraph：本地实装 **1.2.1** / langgraph-checkpoint 4.1.1 / langchain-core 1.4.0；requirements 却写 `langgraph>=0.2` → **锁版本**，新增 `langgraph-checkpoint-postgres`。
- [pg_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/pg_client.py)：`ENGINES` dict 三引擎 + `init_pg/close_pg` 遍历模式 → 加 app 引擎成本很低。
- [llm_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/llm_client.py)：裸 httpx，超时硬编码（30/60s），已有 Redis LLM 缓存与本地模型→flash 降级 → 套 resilience 层。
- redis_client.py：已有滑动窗口限流 + RedisCircuitBreaker + 任务队列原语（**无 worker 消费**）。
- gateway.py：单文件 29 端点，SSE 三套路（chat/debate/contract），无 request-id、返回体不统一。
- 前端：Next.js App Router，状态在 localStorage（4 个 key），无新增运行时依赖需求（EventSource 原生）。
- compose：7 服务（redis/postgres(pgvector)/qdrant/litellm-db/litellm/fastapi/frontend），无 Kafka/worker/可观测性。

---

## 3. 任务卡（按阶段；ID 用于跟踪）

### P0 — 工程地基（后端为主，前端仅 http 客户端）

| ID | 任务 | 主要文件 | 验收 |
|---|---|---|---|
| T0.1 | 版本与镜像对齐：Dockerfile→python:3.12-slim；requirements 锁 `langgraph>=1.2,<2`、新增 aiokafka/tenacity/structlog/langgraph-checkpoint-postgres/opentelemetry-* | `backend/Dockerfile`、`backend/requirements.txt` | 镜像构建成功；`pip check` 通过 |
| T0.2 | 新库与 schema：PG 建 `legalmind_app`；`04-app-schema.sql`（conversations/conversation_members/messages/agent_registry/case_roster_templates/memories/collab_turns/host_decisions）；种子 10 Agent + 8 模板 | `sql/init/00-create-dbs.sql`（加库）、`sql/init/04-app-schema.sql`（新）、种子 SQL | 全新 compose up 自动建库建表、种子可查 |
| T0.3 | pg_client 加第四引擎 app_engine + app_session_factory + ORM 模型 | `core/pg_client.py`、`core/config.py`（APP_DB_URL） | 四引擎 init/close 通过 |
| T0.4 | 统一信封与错误码：`ApiResponse{code,message,data,request_id}`、`core/errors.py` 错误码枚举（0/401xx/429xx/502xx/503xx/504xx/50901…）、业务异常、全局处理器 | `core/response.py`、`core/errors.py`、`main.py` | 单测覆盖各错误码映射 |
| T0.5 | resilience：tenacity 异步重试（0.5/1/2s+jitter，3 次，仅幂等/首字节前）、超时分层（5/30/120/300s）、按服务名复用熔断器、降级链；接入 llm_client 与 ocr_service | `core/resilience.py`（新）、改 `llm_client.py`、`ocr_service.py` | 注入 500 验重试次数与 50301 熔断 |
| T0.6 | structlog JSON + X-Request-ID 中间件（contextvar 贯穿，Kafka header/Redis payload/前端短码） | `core/logging.py`（新）、`main.py` | 日志 grep 同一 request_id 跨组件 |
| T0.7 | OTel 常开：FastAPI/httpx/SQLAlchemy 自动埋点 + W3C traceparent；compose 加 jaeger(all-in-one,:16686)；worker 同配置 | `core/tracing.py`（新）、`main.py`、compose | Jaeger 可见一条 HTTP→LLM trace；关 jaeger 容器业务正常 |
| T0.8 | Kafka 接入：apache/kafka:3.7.2 KRaft 服务 + 3 topic(collab-turns/memory-events/doc-tasks)×3 partition；`core/events.py` aiokafka 封装（懒连、失败降级不阻断）；ENABLE_KAFKA 开关 | docker-compose.yml、`core/events.py`、`.env.example` | 开关 false 可正常启动；true 时收发自测通过 |
| T0.9 | LangGraph Checkpointer：AsyncPostgresSaver 连 legalmind_app，startup `setup()` 建 checkpoint 表 | `core/checkpoint.py`（新）、`main.py` | 中断的图状态可在 PG 三表中查到 |
| T0.10 | Worker 骨架：`worker/main.py --role`、:8001 healthz/metrics、10s Redis 心跳(TTL30s)、优雅停机；compose 三 worker（同镜像不同 command） | `worker/main.py`（新）、compose | 三 worker 起、心跳可见、kill 后状态正确 |
| T0.11 | 探针：/healthz（不查依赖）、/readyz（Redis/PG/Qdrant/Kafka 生产者）；Prometheus 指标补齐（http/llm/retry/cb/turn/agent/kafka_lag/heartbeat） | `main.py`、`core/metrics.py` | 断 Redis 时 readyz=503、healthz=200 |
| T0.12 | **旧 29 端点全量穿信封**（业务负载下沉 data，HTTP 语义不变）；三类 SSE error 事件统一；前端 `lib/http.ts` 统一解包+401/429/幂等重试 | `routers/gateway.py`、前端 `app/lib/http.ts`（新）并改全部调用点 | **回归红线**：合同审查三栏+SSE、庭审补证流行为不变 |

**P0 完成标志**：`ENABLE_KAFKA=false` 下现网全部功能行为不变，但日志/信封/重试/追踪/探针已就位；`true` 时三 worker 空转待命。

**执行中记录的遗留项（T0.6 发现，T0.12 必须收口）**：

- `main.py` 旧的 `@app.exception_handler(Exception)`（`global_exception_handler`，裸返回 `{detail,type}`）注册在 T0.4 `register_exception_handlers()` **之后**，覆盖了信封兜底 handler（信封版对 EnvelopeRouter 请求应返回 `code=50000` 信封）。当前无 EnvelopeRouter 线上路由，故暂无行为影响；T0.12 旧端点穿信封时**必须二选一**——建议删除旧 handler，旧路由的非信封响应改由 `response.py` 中 `_is_envelope_request` 分支复刻。收口时需同时验证：信封 500 响应体 `request_id` 与 `X-Request-ID` 响应头一致。
- 该响应头依赖 T0.6 的最外层纯 ASGI 包裹 `app = RequestContextMiddleware(app)`（位于文件末尾）。**不可退回 `app.add_middleware(...)`**：Starlette 的 `ServerErrorMiddleware` 恒为内建栈最外层，未捕获异常经更外层 `send` 发 500 后再 re-raise；中间件若在其内侧，500 响应会被绕过（无 request-id 头、读不到真实状态码、contextvar 在异常处理器执行前被 reset）。T0.7 接 OTel 的 FastAPI instrumentor 时注意保持该包裹顺序。

### P1 — 群组协同与动态调度（主体）

| ID | 任务 | 主要文件 | 验收 |
|---|---|---|---|
| T1.1 ✅ | （已交付并验收）会话/群/成员/消息 API + Redis 热缓存 + 同群轮次锁（冲突 50901）；SSE 短票据（60s）+ Stream(MAXLEN 500) 回放 + PubSub 桥 + 15s ping。**T1.1 补丁（随 T1.2 同批提交，见 §3.2）：① `my_role`/`target_agent_id`（B3/B1 数据层）；② 前端刷新状态恢复（D16）** | `routers/conversations.py`、`routers/collab.py`（新）、`core/redis_client.py`、前端 `lib/{http,sse}.ts`、stores（补丁） | 刷新/重连消息不丢不重（12 新用例 + 全量 166 通过 + 真机冒烟 11 项）；补丁后刷新不丢 |
| T1.2 ✅ | **Agent 注册表与案情模板服务**（详见 §3.1）：① `registry.py` 从 `agent_registry`/`case_roster_templates` 加载并校验（roster 成员必须存在、host 必在 roster、court host=judge）；② `routers/agents.py` 只读接口：`GET /api/agents`（10 个）、`GET /api/agents/{id}`、`GET /api/agents/templates`（8 模板卡）；③ **B3** 建群补 `my_role`（用户扮演的 agent_id，可空，∈roster）；④ **B1 数据层**：`direct` 会话补 `target_agent_id`（∈10 Agent）；⑤ 加人/移除即时改变白名单 | `routers/agents.py`（新）、`services/collab/registry.py`（新）、`sql/init/04-app-schema.sql`（改）、`core/pg_client.py`（改）、`routers/conversations.py`（改）、`main.py`、`tests/test_registry.py`（新） | F8/F9（见 §3.1 验收）；已交付，全量 184 通过 |
| T1.3 ✅ | 星型图 `build_collab_graph()`：prepare/**host**/**scheduler（隐藏排序，D14）**/ask_user/conclude + 节点工厂(agent:*×注册表, tool:*)；**host 发言 →（程序 OK 时）scheduler 决策 next_speaker/续轮 → agent/tool → 回 host**；仅固定 spoke→host 回边；绑 AsyncPostgresSaver | `services/collab/graph.py`、`state.py`（新）、`tests/test_collab_graph.py`（新） | 图结构评审通过：`builder.edges` 中 host/scheduler **零固定出边**；scheduler 不在 `agent_registry`、不可见；三类护栏 + D15③ 降级兜底单测 11 项全绿（全量 195 通过）；真库 10 Agent/8 模板构图 + court 默认顺序冒烟通过 |
| T1.4 ✅ | HostSkill：人设发言 + 程序指令（`ask_user/verdict/conclude`）、容错提取、护栏、同 super-step 反馈修复一次；**新增 `SchedulerSkill`（隐藏排序智能体）**：中性无角色、无气泡、flash 模型，输出 `next_speaker` + `continue_round` + `reason`，白名单/轮次护栏、失败降级兜底、**每次决策落 `host_decisions` 审计（D15）**；host 人设按模板注入（D10）：court→judge、普通会商→调解员/法务分析师 | `services/collab/host_skill.py`、`scheduler_skill.py`、`prompts.py`、`audit.py`（新） | F13；非法/越权指令 100% 被护栏裁决；**scheduler 不产生气泡、不出现在成员列表**；14 新用例 + 全量 209 通过（详见 §3.4） |
| T1.5 ✅ | Agent 节点工厂零侵入映射：统一群上下文块 → 现有 9 Skill 入参；流式 message 事件 + 确定性 event_key；**B1：`direct` 会话按 `target_agent_id` 仅驱动该 Agent（单聊轮次只调它、不拉他人）** | `services/collab/agent_nodes.py`、`tool_nodes.py`（新）、`graph.py`/`state.py`/`conversation_store.py`/`pg_client.py`/`sql/init/04-app-schema.sql`（改）、`tests/test_collab_agent_nodes.py`（新） | F2 顺序气泡；ON CONFLICT 不重复；单聊只出该 Agent 一条流（11 新用例 + 全量 220 通过，详见 §3.5） |
| T1.6 ✅ | 恢复引擎（双模式共用执行器）：turn 状态机(running/interrupted/completed/failed)+租约+attempts/DLQ；`interrupt()/Command(resume=)`；checkpoint 续跑；checkpoints 列表与 fork API；**B2 接管式扮演：轮到 `my_role` 时 `interrupt` 挂起→用户输入后以该角色身份 resume 续跑（`metadata.actor_agent_id`）；「交还给 AI」＝`Command(update)` 撤销接管标志后自动续跑**；**辩论恢复特殊规则（D15）：① 恢复/续跑严格保序不跳人（未发言者按原序补齐、已发言不重生成）；② 每次排序决策落 `host_decisions` 审计；③ scheduler 失败降级兜底（回退模板默认顺序/主持人兜底），不中断整轮**（**M1–M4 ✅ 全部交付，见 §3.6**） | `services/collab/runner.py`、`worker/consumers/collab.py`（新） | F4/F11/F12（含 kill worker 故障演练）；接管暂停/交还闭环；**辩论中断后保序不跳人、无重复气泡** |
| T1.7 ✅ | court 模板配置化（host=judge；**scheduler 打散串行、庭审用语中性**；JudgeSkill 增 collab_mode 提示词分支与程序指令字段；verdict→JudgmentReportSkill；补证卡片群内化）（**已交付，见 §3.7**） | 改 `agents/judge_skill.py`（仅新增分支）、`services/collab/templates/{__init__,court}.py`（新）、`services/collab/graph.py`（向后兼容注入点） | F7 新旧两路回归 |
| T1.7⁺ ✅ | **生产图全局接线（集成收口）**：`get_collab_graph()` 由默认桩改为**真实件**，按模板 `adapter` 分派（court→法官/庭审排序/补证卡片/判决书；通用→HostSkill/SchedulerSkill），接线 AgentNodeRunner/ToolNodeRunner/`host_decisions` 审计落库；**同一张编译图服务所有模板**（**已交付，见 §3.8**） | `services/collab/production.py`（新）、`services/collab/graph.py`（改：ask_user 支持 async interaction_card + `get_collab_graph` 真实装配） | 分派正确性 + 图可编译/异步卡片 6 新用例；全量 **259 通过** |
| T1.8 | 前端三栏 IA 与消息中心（对应 D8–D12，**收敛范围见 D17–D19**）：图标导航、会话列表（**direct/group 图标区分**）、**建群向导三步（含「我不扮演／我扮演某人」）**、`ConversationView`（**单聊/群聊共用**）、气泡/typing/工具卡/纪要卡/@、**接管发言角标「你（扮演 XX）」+「交还给 AI」按钮**、右栏群管理与 Agent 时间线（含主持人 reason）、补证卡片、失败重试、"回到此轮" | `app/messages/*`、`components/collab/*`、stores、`lib/sse.ts`（新） | 选"合同纠纷"自动建群 4 Agent；F1-F8 手测 |
| T1.9 | 会商纪要与引用卡；结束会商按钮（注入 goto=conclude） | 同 T1.8 + `services/collab/minutes.py` | F6 |

#### 3.1 T1.2 详细拆解（已交付 ✅）——Agent 注册表与案情模板服务

> 本卡是「建群向导」与「编排器白名单」的**唯一数据源**，并把前端设计派生出的两个字段（`my_role`／`target_agent_id`）落到接口层。**不做编排逻辑**（留给 T1.3–T1.7）。

**交付偏离记录（已告知，未反对）**：计划原写「host ∈ roster」，但 court 种子 host=judge 而 roster 只列原被告/书记员，且 store 的 `create_conversation` 本就自动把 host 并入成员 → 校验规则放宽为**「主持人必须已注册」**。若日后要严格，需补 court 种子并 UPDATE。

**目标**：把 10 个 Agent 与 8 个案情模板从 SQL 种子变成可查询、可校验、可复用的服务；编排器与前端向导统一从它取数，杜绝任何硬编码名单。

**交付 1 — `backend/app/services/collab/registry.py`（新）**
- `AgentRegistry`：从 `agent_registry` 表加载 10 个 Agent（`agent_id / name / role_label / description / skill_ref / persona / model_pref / is_tool / sort_order / avatar / enabled`），进程内缓存 + 显式失效刷新；提供 `get(agent_id)`、`all(include_disabled=False)`、`by_ids(ids)`、`tool_agents()`。
- `TemplateRegistry`：从 `case_roster_templates` 加载 8 模板（`case_type / name / icon / description / host_agent_id / roster[{agent_id,stage,order}] / max_rounds / opening_enabled / minutes_enabled / adapter / enabled`），仅返回 `enabled=true`。
- **加载即校验**（失败快速暴露，不留到运行期）：① 模板 roster 内每个 `agent_id` 必须存在于注册表；② `host_agent_id` 必须 ∈ roster；③ `court` 模板 host 必须 = `judge`。
- 供编排器复用的小工具：`default_roster(case_type)`、`resolve_host(case_type)`、`whitelist(members)`（把群成员映射成 **scheduler 可 goto** 的白名单集合，D14 后由 scheduler 消费；host 仅出程序性建议，T1.4 用）。

**交付 2 — `backend/app/routers/agents.py`（新，`EnvelopeRouter(prefix="/api/agents")`，JWT 鉴权、只读、无副作用）**
- `GET /api/agents`：列出 Agent（支持 `?is_tool=`、`?q=` 过滤）→ 供「Agent 通讯录」页与建群向导第二步勾选。
- `GET /api/agents/{agent_id}`：单个详情（名称/角色标签/能力/是否工具型/头像）。
- `GET /api/agents/templates`：8 个模板卡数据（icon/name/description/默认 host 与 roster 摘要/轮数）→ 供向导第一步与「发起多 Agent 协同」。
- 在 `main.py` 注册该路由。

**交付 3 — B3：建群 `my_role`（改 `sql/init/04-app-schema.sql` + `core/pg_client.py` + `routers/conversations.py`）**
- schema/ORM：`conversations` 表（及 `Conversation` 模型）加 `my_role VARCHAR(64) NULL`（用户扮演的 agent_id，空＝不扮演）。
- `CreateConversationRequest` 增加：`template_id`（＝case_type，选填；给了就按模板自动铺 roster 与 host）、`my_role`（选填；**校验 ∈ 最终 roster**，否则 `40004 InvalidParams`）。
- 语义：空＝不扮演（默认）；指定＝接管式扮演，**仅 `group` 有效**，`direct` 传 `my_role` 报 40004；供 T1.6 判断「轮到谁暂停」。

**交付 4 — B1 数据层：单聊 `target_agent_id`（改同文件）**
- schema/ORM：`conversations` 表加 `target_agent_id VARCHAR(64) NULL`。
- `CreateConversationRequest` 增加 `target_agent_id`：`type=direct` 时**必填**且 ∈ 10 Agent；`type=group` 时**禁止**（否则 40004）。
- 本卡只落字段与校验，「单聊轮次只调该 Agent」的执行逻辑归 T1.5。

**交付 5 — 即时白名单（不新增表，复用 T1.1 成员接口）**
- 群内加人（`POST /{id}/members`）/移除（`DELETE /{id}/members?agent_id=`）后，registry 解析出的白名单在**同一请求周期内**即可见；加人校验 `agent_id` 必须 ∈ 注册表（未知 Agent → 40004）。

**验收**
- **F8**：`GET /api/agents` 返回 10 项、`GET /api/agents/templates` 返回 8 项，字段齐备可供向导直接渲染。
- **F9**：加人/移除后白名单即时变化；加未知 Agent → 40004。
- `my_role` 不在 roster → 40004；`direct` 缺 `target_agent_id` → 40004；`group` 带 `target_agent_id` 或 `my_role` → 40004。
- 新增单测 `tests/test_registry.py`（注册表加载、模板→roster/host 映射、三类校验）；`tests/test_conversations_api.py` 补 `my_role`/`target_agent_id` 用例。
- 全量 pytest **不破坏 T1.1 基线**（12 用例 + 既有 154 全绿）。

**主要文件**：`services/collab/registry.py`（新）、`routers/agents.py`（新）、`sql/init/04-app-schema.sql`（改：conversations 加 `my_role`/`target_agent_id`）、`core/pg_client.py`（改：ORM 同步）、`routers/conversations.py`（改）、`main.py`（注册 agents 路由）、`tests/test_registry.py`（新）、`tests/test_conversations_api.py`（补）

**明确不做**（留给后续卡）：host 白名单消费（T1.4）、单聊只调 target Agent（T1.5）、接管暂停/交还（T1.6）、前端向导 UI（T1.8）。

#### 3.2 T1.1 补丁（随 T1.2 同批提交）——前端刷新状态恢复

> 现网问题：**已登录用户点击刷新后界面数据丢失**。根因：前端会话/消息仍主要依赖浏览器内存（Zustand）与 localStorage，刷新后未从 T1.1 已交付的**服务端权威存储**重新拉取，SSE 也未以 `last_id` 重连。本补丁为**纯前端状态恢复**，不改后端契约（除 §3.1 的 `my_role`/`target_agent_id` 两列）。

**交付**
1. 进入 `/messages` 时：`lib/http.ts` 校验 JWT（401 → 跳登录）→ `GET /api/conversations?status=active` 拉会话列表 → 选中「上次打开的会话」（`useUIStore` 记 id）。
2. 恢复消息：`GET /api/conversations/{id}/messages`（首页命中服务端 Redis 热缓存）→ 渲染；再 `POST /api/collab/conversations/{id}/events/ticket` 换票 → `lib/sse.ts` 以 `last_id`（本会话已收到的最大 event_id）重连 `GET .../events`，回放缺口并续推实时，**按 event_id 去重**。
3. 鉴权持久化：token 存 localStorage（**按用户名隔离**，沿用既有 `{key}:{username}` 规范）；刷新后先 hydrate 再用。
4. 不重复渲染：SSE 回放事件与已拉取消息按 `id` 去重；前端对增量消息以 message_id **追加合并，严禁整包替换**（对齐 S1）。

**验收**
- 硬刷新（F5/Ctrl+R）后：仍在同一会话、历史消息完整、**无重复气泡**；断网 30s 内重连不丢不重（对齐 O4）。
- 未登录访问 `/messages` → 跳登录页。

**主要文件**：`frontend/app/lib/{http,sse}.ts`、`frontend/store/{useSessionStore,useCollabStreamStore,useUIStore}.ts`、`frontend/app/messages/*`

**说明**：与 T1.2 同批提交；B3 `my_role` / B1 `target_agent_id` 的后端半见 §3.1 交付 3/4。

#### 3.3 T1.3 交付记录（已交付 ✅）——星型图与护栏

**交付**
1. `services/collab/state.py`（新）：`CollabState`（messages/roster/round/max_rounds/spoken/host_directive/scheduler_directive/memories/retrieved/pending_question/force_stop_reason/events/budget）+ `initial_state()`；`spoken`（保序并集）与 `events`（只增）用自定义归并器，供 D15① 保序与 D15② 审计。
2. `services/collab/graph.py`（新）：`build_collab_graph()` 装配 prepare/host/scheduler/ask_user/conclude + 节点工厂（`agent__*` 按注册表、`tool__*` 按工具 Agent）+ 固定回边（所有辐条/ask_user → host）；`host` 与 `scheduler` **零固定出边**，去向全部由 `Command(goto=)` 运行时决定；默认绑 `AsyncPostgresSaver`（未就绪则不持久化）。
3. 三类护栏内建：白名单（roster 去主持人 ∪ 工具节点）、`max_rounds`/预算硬顶、非法目标回落模板默认顺序（= D15③ 降级兜底，scheduler 抛异常亦走此路径，不中断整轮）。
4. `tests/test_collab_graph.py`（新，11 用例）：结构评审 + 默认顺序收敛 + 轮次硬顶 + verdict/ask_user 分支 + 越权回落 + 异常降级 + 移除成员即时生效 + `interrupt()/resume` 闭环。

**实施偏离（2 处，均因框架约束/数据驱动原则）**
- LangGraph 1.x 保留 `:` 作节点命名空间分隔符（`NS_SEP`），§2.1 规格的 `agent:*` / `tool:*` 落地为 `agent__*` / `tool__*`（仅图内部标识，对外统一用 `agent_id`）。
- 工具节点按注册表 `is_tool` 生成 `tool__legal_researcher` / `tool__case_searcher`，不硬编码 `tool:legal_search` / `tool:case_search`（与「杜绝硬编码名单」一致）。

**可注入扩展点（供 T1.4/T1.5/T1.6 复用，本卡只给最小可跑桩）**：`host_advisor`（HostSkill）、`scheduler`（SchedulerSkill）、`agent_runner`（真实 Skill 映射）、`tool_runner`、`decision_recorder`（`host_decisions` 落库）。

#### 3.4 T1.4 交付记录（已交付 ✅）——HostSkill + SchedulerSkill

**目标**：把 T1.3 留在图里的两个可注入扩展点（`host_advisor` / `scheduler`）替换成真实能力——主持人人设发言 + 程序性指令、隐藏排序智能体的 next_speaker/续轮决策，并把每次决策落 `host_decisions` 审计（D15②）。

**交付**
1. `services/collab/prompts.py`（新）：提示词与容错提取工具。`_iter_bare_json()` 从**最早的 `{`** 正序扫描取**最外层** JSON 对象；`_iter_fenced()` 命中 ```json 围栏时**整体剥离**（`text[:m.start()] + text[m.end():]`），供 S1 流式末尾 directive JSON 缓冲剥离复用；`extract_json_object()` / `split_utterance_and_json()` 容错提取；`build_host_system_prompt()` / `build_host_user_prompt()` / `build_host_repair_prompt()`（host 人设按模板注入：court→judge、其余→模板 host）；`SCHEDULER_SYSTEM_PROMPT` + `build_scheduler_user_prompt()` + `build_scheduler_repair_prompt()`。
2. `services/collab/host_skill.py`（新）：`HostSkill`。`build_messages(state)` 返回 `(messages, agent, template)` 供 T1.6 流式复用；`speak_and_decide(state)` → `{utterance, directive, ask_user, round_summary, reason, parse_ok, parse_failed, repaired, raw_output, latency_ms}`；程序指令枚举按模板区分（court：`continue/ask_user/verdict`，generic：`continue/ask_user/conclude`）；解析失败先注入 repair prompt 反馈修复**一次**，连续两次非法 → `directive="conclude", parse_failed=True`；**LLM 异常直接抛出**（交 graph super-step / T1.6 恢复），节点内不吞错。
3. `services/collab/scheduler_skill.py`（新）：`SchedulerSkill`（模型 `deepseek-flash`）。`decide(state, candidates)` → `{next_speaker, continue_round, reason, raw_output, latency_ms, repaired, parse_failed}`；模块级 `_validate(raw, candidates)`：`next_speaker` 必须 ∈ candidates，`continue_round=true` 而无 next 视为非法；修复一次后仍非法 → `next_speaker=None, continue_round=False, parse_failed=True`；LLM 异常直接抛出，由 graph 节点降级为模板默认顺序（D15③）。
4. `services/collab/audit.py`（新）：`record_host_decision(record)` 落 `HostDecision`（`parsed_directive` 内 `setdefault("kind", ...)`；`raw_output` 截断 `MAX_RAW_OUTPUT=4000`；非法 uuid 静默跳过；写库异常仅告警 fail-open，不阻断业务）。
5. `services/collab/graph.py`（改）：接入真实 Skill 后，scheduler 词汇表由节点名改为 **agent_id**；host 口语发言写入气泡消息；审计补 `raw_output`/`latency_ms`；预算记账（`_charge_budget`）；非法枚举回落 `conclude`。
6. `tests/test_collab_skills.py`（新，14 用例）：JSON 容错提取、围栏剥离、host 正常/修复/双失败/非法 verdict/LLM 抛出、scheduler 正常/越权/非法/降级、audit 落库与 fail-open、真实 Skill 接入图后 scheduler 无气泡。

**实施偏离（3 处）**
- scheduler 候选/返回词汇表用 **agent_id**（非节点名），与「对外一律用 agent_id」一致，也让白名单校验与注册表天然对齐。
- `host_decisions` 表无 `kind` 列（T0.2 schema 已定稿），故 `kind` 存入 `parsed_directive["kind"]`，不新增迁移。
- 工具节点命名保持 T1.3 的**数据驱动**（`tool__*` 按 `is_tool` 生成），不硬编码。

**自动测试**：`tests/test_collab_graph.py` + `tests/test_collab_skills.py` 共 25 用例全绿；全量后端 **209 passed**。前端本卡**零改动**，故无前端测试项。

#### 3.5 T1.5 交付记录（已交付 ✅）——Agent / Tool 节点工厂零侵入映射

**目标**：把 T1.3 留在图里的两个可注入扩展点（`agent_runner` / `tool_runner`）替换成真实能力——统一群上下文块 → 现有 9 Skill 流式方法入参；每个 Agent 发言走 **S1 三事件 token 级流式**（`message_start` → 多帧 `message_delta` → `message_end`）并按**确定性 `event_key`** 幂等落库；工具辐条按 `skill_ref` 映射到法规/类案检索链路；并落地 **B1 单聊**执行层（`direct` 会话只驱动 `target_agent_id`）。

**交付**
1. `services/collab/agent_nodes.py`（新）：**群上下文块** `GroupContext`（`case_type/case_type_label/title/question/transcript/materials/memories/host_guidance/instruction` + `speeches_by()` + `render()`，§3.2 版式）；`build_group_context(agent, state)` 纯函数构造（transcript 从 `AnyMessage.additional_kwargs` 提炼、问题取最近用户消息、资料从 `retrieved` 渲染、指引取 `host_directive`）；**零侵入 adapter** `SKILL_STREAM_ADAPTERS`：把统一上下文块映射为 `LegalAnalyzer.analyze_stream(query, context)`、`RegulatoryResearcher.research_stream(query, area)`、`MediatorSkill.propose_mediation_stream(...)`、`PlaintiffSkill.opening/rebuttal_stream(...)`、`DefendantSkill.opening/rebuttal_stream(...)`、`JudgeSkill.preside_opening_stream(...)`、`JudgmentReportSkill.generate_judgment_stream(...)` 的**现有入参**（`query/context`、`case_facts/focus_points/legal_knowledge` 等），**不改动任何 Skill 人设 prompt**；`resolve_adapter()` 按注册表 `skill_ref` 取适配器，无匹配走 `_stream_generic`。**确定性幂等键** `make_event_key(turn_id, round, agent_id, seq) = {turn_id}:r{round}:{agent_id}:{seq}`、`message_id_for(event_key) = uuid5(ns, event_key)`。**`AgentNodeRunner`**：`__call__(agent, state)` → 无会话上下文时 `_stream_only`；否则 `_stream_persist`——**先查库后发**（`get_message_by_event_key` 命中即复用，不重复 emit/不重复调 LLM）→ emit `message_start`（含 `message_id/event_key/round/sender`）→ 逐 chunk emit `message_delta` → emit `message_end`（定稿 content）→ `insert_message_once`（ON CONFLICT）→ 热缓存 `push_recent_message`（try/except fail-open）。
2. `services/collab/tool_nodes.py`（新）：`SKILL_DOMAINS = {RegulatoryResearcher: law, CaseSearchSkill: judge}`（数据驱动按 `skill_ref`）；`ToolNodeRunner` 用 `deepseek-flash` 取 chat model，调 `retrieve_legal_knowledge(query, top_k, use_hyde, domain)`；**失败降级**——检索异常返回空结果 + 告警，不让整轮中断。
3. `services/collab/graph.py`（改，B1 执行层）：`_allowed_candidates`、`host_node`、`conclude_node` 增加 `direct` 分支——host 短路**直接派发** `target_agent_id`（不调 host/scheduler）、白名单仅含唯一目标 Agent（不追加工具节点）、目标已发言即 `force_stop_reason="direct_done"` 收尾；**direct 无主持人 → conclude 不产生「宣布结束」气泡**。
4. `services/collab/state.py`（改）：`CollabState` 新增 `conv_type` / `target_agent_id`（B1 执行依据）；`initial_state(...)` 增同名参数。
5. `core/pg_client.py` + `sql/init/04-app-schema.sql`（改）：`messages` 表新增 `event_key VARCHAR(128)`；新增幂等迁移 `ALTER TABLE messages ADD COLUMN IF NOT EXISTS event_key VARCHAR(128)` 与**唯一索引** `uq_messages_event_key ... WHERE event_key IS NOT NULL`。
6. `services/collab/conversation_store.py`（改）：协议新增 `insert_message_once(...)`（`pg_insert(...).on_conflict_do_nothing(index_elements=["event_key"])`，冲突→返回 None）与 `get_message_by_event_key(...)`；`serialize_message` 增 `event_key`。
7. `tests/test_collab_agent_nodes.py`（新，11 用例）：群上下文块渲染与构造、`event_key`/`message_id` 确定性、adapter 映射（含无匹配走通用人设）、S1 三事件顺序 + 幂等落库、「先查库后发」命中复用不重复调 LLM、ON CONFLICT 冲突返回 None、adapter 调现有 Skill 入参正确、工具辐条领域映射 + fail-open + 未知 `skill_ref` 不触发检索、B1 direct 只出目标 Agent 一条流且 conclude 无主持人气泡、F2 群聊气泡严格按模板顺序。

**实施偏离（已记录）**
- **通用人设 adapter 兜底**：`chat_rag`、`CaseSearchSkill`、`ContractReviewSkill` 等**无现成流式方法**的 Skill，走 `_stream_generic`（`persona` + 群上下文块 → `LLMClient.chat_stream`），保证 S1 流式不破；这些 Skill 日后若补流式方法，只需在 `SKILL_STREAM_ADAPTERS` 注册，无需改图。
- 事件发射器 `Emitter` 默认走 Redis Stream + Pub/Sub（`append_conv_event`），测试注入假实现；`push_recent_message` 热缓存失败仅告警，不影响权威落库。

**自动测试**：`tests/test_collab_agent_nodes.py` 11 用例全绿；全量后端 **220 passed**。前端本卡**零改动**，故无前端测试项。

#### 3.6 T1.6 交付记录（M1–M4 已交付 ✅）——恢复引擎

**目标**：以 `collab_turns` 台账为权威，把「用户一次发言」驱动成一个可中断、可续跑、可重试、可回退（fork）的轮次；**Kafka 消费与进程内执行共用同一执行器**（双模式）。M1 = turn 执行器核心（状态机 + 租约心跳 + 中断/续跑 + attempts/DLQ + checkpoint 时间线/fork）；M2 = B2 接管式扮演。

**M1 交付**
1. `core/config.py`（改）：新增 `KAFKA_TOPIC_TURNS_DLQ`、`TURN_LEASE_SECONDS=90`、`TURN_HEARTBEAT_INTERVAL=10.0`、`TURN_MAX_ATTEMPTS=3`、`TURN_HISTORY_LIMIT=20`。
2. `core/redis_client.py`（改）：新增 `refresh_turn_lock(conversation_id, holder)`——`SET ... XX` 语义的锁续租（执行期间心跳同时续期轮次锁）。
3. `services/collab/turn_store.py`（新）：状态常量（`TURN_RUNNING/INTERRUPTED/COMPLETED/FAILED`、`TERMINAL_STATUSES`、`OPEN_STATUSES`、`MODE_INPROCESS/MODE_KAFKA`）+ `TurnStore` 协议 + `PgTurnStore`（`create_turn/get_turn/get_open_turn/list_turns/update_turn/heartbeat/increment_attempts/claim_orphan_turns`）——`claim_orphan_turns` 用**两段式**（`SELECT ... FOR UPDATE SKIP LOCKED` → `UPDATE by ids`）避免长事务持锁；`increment_attempts` 原子自增 returning。
4. `services/collab/runner.py`（新，核心）：`TurnRunner`（图/台账/会话 store/注册表/emit/worker_id/锁函数/DLQ 全部**可注入**）+ `TurnOutcome` + `make_turn_runner` 工厂。`execute_turn`：终态幂等跳过 → 轮次锁双重保险 → `_resolve_input`（resume→`Command(resume=...)`；有 checkpoint→`None` 续跑；否则从 messages 表播种历史建 `initial_state`）→ `_start`（状态落 running + `status` 事件）→ `_start_heartbeat` → `_drive`（`astream(stream_mode="updates")` 捕获 `__interrupt__`）→ `_on_success`/`_on_interrupt`/`_on_failure`。`resume_turn`/`retry_turn`/`recover_orphans` 复用同一入口。`list_checkpoints`（`aget_state_history` 时间线）/`fork_turn`（从指定 checkpoint 在新 thread 重跑，修正事实 + 隔离审计）。
5. `tests/test_collab_runner.py`（新，8 用例）：正常完成 / 终态幂等跳过 / 锁冲突跳过 / `ask_user` 中断→resume 续跑闭环 / 失败 attempts 累计→DLQ（含 `retryable` 事件与 DLQ payload）/ 租约过期孤儿认领续跑 / checkpoint 时间线 / 从 checkpoint fork。

**实施偏离（已记录）**
- **checkpoint `thread_id` 取 `turn_id`（非 `conversation_id`）**：每轮 `spoken`（`append_unique`）/`round`/`events` 为递增归并器，复用会话级 thread 会导致**跨轮状态串味**（上一轮 `spoken` 残留使新轮无处可点）；故按轮隔离 thread，**跨轮上下文由执行器从 messages 表播种最近 `TURN_HISTORY_LIMIT` 条**（DB 为权威，§3.1）。属对 checkpoint spec §2.2 的偏离。
- **中断（interrupted）即放锁**：中断不占 worker，用户下一条消息据 `get_open_turn` 路由为 resume（M3 落地）。
- **DLQ fail-open**：DLQ 发布失败仅告警，不阻断主流程。
- 单测用假台账/假会话 store/假锁 + `InMemorySaver` 真图，**不依赖 DB/Redis/LLM**。

**M2 交付（B2 接管式扮演，D11）**
1. `services/collab/graph.py`（改）：agent 节点工厂新增**接管分支**——当 `next_speaker == state.my_role` 时调用 `interrupt({type: "takeover", agent_id, agent_name, question})` 暂停（**AI 不代其生成**）；resume 值非「交还」时，该发言以 **`sender_type=user` + `metadata.actor_agent_id`** 落 transcript（`HumanMessage`，D11 版式）；resume 值为「交还给 AI」（`{"action":"hand_back"}` / `{"hand_back":true}`）时**撤销接管标志**（本 turn 内置空 `my_role`）后自动续跑，改由 `agent_runner` 以该角色身份生成（`sender_type=agent`）。
2. 新增模块常量 `TAKEOVER_TYPE` 与辅助 `_is_hand_back()` / `_takeover_text()`（兼容纯字符串 / `{"text"|"content"}`）。
3. `tests/test_collab_runner.py`（补 2 用例）：`test_takeover_interrupt_then_resume_as_role`（暂停 → `resume` 文本 → transcript 落 `sender_type=user` + `actor_agent_id`）、`test_takeover_hand_back_generates_ai_message`（交还 → 撤销标志 → AI 代生成，无用户接管气泡）。

**实施偏离（M2，已记录）**
- 「交还给 AI」的**进程内 `my_role` 置空仅作用于本 turn**（thread 按轮隔离，下一轮从 `conversations.my_role` 重新播种）；**跨轮持久化「撤销接管」由 M3 API 更新 `conversations.my_role=NULL`** 承接。

**自动测试**：`tests/test_collab_runner.py` 10 用例全绿；全量后端 **230 passed**（基线 228 + 2，无回归）。前端本卡**零改动**。

**M3 交付（API + SSE 事件接入 + checkpoints/fork 端点）**
1. `services/collab/runner.py`（改）：新增 `_inline_worker_id()`（`inline-{hostname}-{pid}` 唯一化，避免多副本各自「孤儿认领」互相抢）+ `get_turn_runner()`/`reset_turn_runner()`——API 路由依赖用的**进程内单例执行器**（Kafka 关时的进程内模式；worker 另建实例）。
2. `services/collab/conversation_store.py`（改）：`ConversationStore` 协议新增 `set_my_role(conversation_id, my_role)`；`PgConversationStore` 实现之——设置/撤销用户扮演角色（`None` ＝撤销接管，承接 B2 跨轮持久化）。
3. `routers/conversations.py`（改，核心）：
   - 依赖 `get_turn_runner`（测试可 override）；`SendMessageRequest.content` 由 `min_length=1` 改为 `default=""`（允许「交还给 AI」空内容控制动作），**非空校验下沉到 handler**；新增 `ForkTurnRequest{checkpoint_id, update?}`。
   - 新增 `_persist_user_message(...)`（`sender_type=user`，`sender_name` 取 `metadata.actor_agent_name`，round=0 → `insert_message` → `push_recent_message` 热缓存 → `_emit_message` SSE）。
   - **重写 `send_message`**：① `runner.store.get_open_turn(conversation_id)` 非 None 且 `status==TURN_INTERRUPTED` → `_resume_message`；非 None 且 running → `TurnLockConflictError`；② 否则 `get_turn_lock_holder` 非 None → 50901；③ `_persist_user_message` → `mode = MODE_KAFKA if settings.ENABLE_KAFKA else MODE_INPROCESS` → `store.create_turn(..., trigger_message_id=...)` → Kafka 开则 `event_bus.publish(KAFKA_TOPIC_TURNS, {...}, key=conversation_id)`（**发布失败降级进程内 `execute_turn`**），关闭则直接 `execute_turn`；返回 `{"message","event_id","turn_id","status"}`。
   - 新增 `_resume_message(...)`：`hand_back` → `set_my_role(conversation_id, None)` + `resume_turn(turn_id, {"action":"hand_back"})`（**控制动作不落聊天气泡**，message=None）；否则 `_persist_user_message` + `resume_turn(turn_id, content)`。
   - 新增 `_require_owned_turn(...)`（turn 不存在或 conversation_id 不符 → `NotFoundError` 40004）。
   - 新增端点 `GET /{conversation_id}/turns/{turn_id}/checkpoints`（返回 `{turn_id,status,checkpoints}`）与 `POST /{conversation_id}/turns/{turn_id}/fork`（body `ForkTurnRequest`；`skipped` → `InvalidParamsError`，否则返回 `{turn_id,status}`）。
4. `tests/test_conversations_api.py`（改）：新增 `FakeTurnRunner`（`store` 属性返回自身；`get_open_turn`→None 等）注入 `app` fixture（`dependency_overrides[conv_mod.get_turn_runner]`），`InMemoryStore` 补 `set_my_role`；`test_send_and_list_messages_uses_cache` 断言由 `turn_id is None` 更新为「起轮次」。
5. `tests/test_collab_turn_api.py`（新，7 用例，真 `TurnRunner` + 真图 + `FakeRedis` + `InMemoryStore`，不依赖 DB/Redis/LLM）：正常发言起轮次 + Stream 含 `message/status/done`；空内容 40001；`ask_user` 中断后下一条消息 resume 同 `turn_id`（Stream 含 `interaction_required`）；接管 resume 落 `metadata.actor_agent_id`（`sender_type=user`）；「交还给 AI」清 `my_role` 且不落接管气泡；checkpoints/fork 端点；未知 turn fork → 404。

**实施偏离（M3，已记录）**
- **生产图接线留作后续集成项**：M3 严格限定 plumbing 范围，`get_collab_graph()` 仍用默认桩（未接真实 `HostSkill`/`SchedulerSkill`/`AgentNodeRunner`），避免范围蔓延。
- `send_message` **空内容校验下沉**到 handler（因 `Field(default="")` 放开），空内容且非 hand_back 才判 40001。
- 「交还给 AI」定为**控制动作**（不落聊天气泡），仅撤销 `my_role` 并 resume。
- Kafka **发布失败降级**进程内执行，保证本地/降级模式下发言不丢。

**自动测试**：`tests/test_collab_turn_api.py` 7 用例全绿 + `tests/test_conversations_api.py` 16 用例全绿（23 passed）；全量后端 **237 passed**（基线 230 + 7，无回归）。前端本卡**零改动**。

**M4 交付（worker 消费器 + 孤儿扫描 + DLQ + kill-worker 故障演练）**
1. `core/config.py`（改）：新增 `TURN_ORPHAN_SCAN_INTERVAL=30.0`（worker 周期扫描僵死轮次间隔）；`core/metrics.py`（改）：新增 `COLLAB_TURN_ORPHAN`（`result=recovered/skipped`）。
2. `worker/consumers/__init__.py`（新）+ `worker/consumers/collab.py`（新，核心）：
   - `handle_turn_message`：据消息 `turn_id` 调 `runner.execute_turn(turn_id)` 驱动整轮（终态幂等由 runner 内部跳过）；缺 `turn_id` 的畸形消息丢弃告警。
   - `consume_turns`：消费 `collab-turns`（group `legalmind-worker-collab`），**手动提交**；逐条 `_dispatch` 异常隔离——**一条毒消息按条 ack 不阻塞后续**；broker 不可达退化为仅心跳（`standby_state=degraded`）。
   - `orphan_scan_loop`：周期 `runner.recover_orphans(limit)` 认领租约过期的 `running` 轮次续跑（worker 崩溃接力，§3.2）；扫描异常不杀进程（下周期重试）。
   - **DLQ**：`attempts` 耗尽时由 runner 发布到 `collab-turns-dlq`（M1 已实现，M4 的消费器不重复处理）。
3. `worker/main.py`（改）：`role=="collab"` 且 `ENABLE_KAFKA` → 接真实消费器 `consume_turns`（memory/doc 仍 `consume_standby` 空转）；**collab 角色无论 Kafka 开关都跑 `orphan_scan_loop`**，与消费器**共用同一 `make_turn_runner`**（进程内降级模式下也可接管僵死轮次）。
4. `tests/test_collab_worker_consumer.py`（新，8 用例，假消费者/假 runner + **真图真执行器**，不依赖 Kafka/DB/Redis）：消息驱动轮次；缺 id 丢弃；消费循环分发 + 提交；毒消息隔离（一条失败其余仍处理并提交）；broker 不可达降级；孤儿扫描恢复并停止；扫描异常存活；**kill-worker 演练**——worker A 跑到图 END 产生 checkpoint 后「僵死」（台账 running + 心跳过期）→ worker B 孤儿扫描认领，从断点续跑至 completed 且**已完成发言不重复**（幂等）。

**自动测试**：`tests/test_collab_worker_consumer.py` 8 用例全绿；全量后端 **245 passed**（基线 237 + 8，无回归）。前端本卡**零改动**。

**T1.6 全文完成**：M1（执行器核心）、M2（B2 接管式扮演）、M3（API/SSE/checkpoints/fork）、M4（worker 消费 + 孤儿扫描 + DLQ + 崩溃演练）均已交付。遗留（后续集成项）——生产图仍用默认桩（未接真实 `HostSkill`/`SchedulerSkill`/`AgentNodeRunner` 到 `get_collab_graph()`）；**该项已于 §3.8 生产图全局接线收口**。

#### 3.7 T1.7 交付记录（M1–M4 已交付 ✅）——court 模板配置化

**目标**：把「模拟庭审」这条业务链做成**一组可注入的适配配置**（而非硬编码业务分支），满足
F7「庭审模板在新星型图完成 开庭→对抗→补证→恢复→裁决 全流程；旧 /debate/stream 回归不变」。

**M1 交付（`agents/judge_skill.py`，仅新增分支）**
- 新增模块常量 `COURT_COLLAB_SCHEDULING_PROMPT`（spec §6「庭审调度权（协同群模式）」**适配 D14**：
  指令字段为程序指令 `round_summary / directive(continue|ask_user|verdict) / ask_user / reason`，
  **移除 spec 原文的 `next` / `search_request`**——前者归隐藏 scheduler，后者由工具辐条承接）；
- 新增纯函数 `build_collab_system_prompt(base=JUDGE_SYSTEM_PROMPT)`；
- `JudgeSkill.__init__` 增参 `collab_mode: bool = False`，True 时拼接种该章节，**默认 False 提示词与
  现有方法全部不变**（旧 `/debate/stream` 链路零回归，A3 红线）。

**M2 交付（`services/collab/templates/`，新）**
1. `templates/__init__.py`：re-export 适配件（新增模板 adapter 只需加模块 + re-export，无需改图）。
2. `templates/court.py`（纯函数 + 可注入工厂，无 IO）：
   - `court_scheduler(state, candidates)`（async，适配图 `SchedulerDecider`）：**打散串行、不跳人、
     中性程序用语**——优先未陈述的原/被告交替（原告优先）→ 双方陈述后传唤 `clerk` → 各方已陈述且
     仍有轮次额度则回到陈述较少一方对辩 → 收敛交主持人裁决；**roster 无原/被告时回退模板默认顺序**。
   - `build_court_host_advisor(...)`：以 `build_collab_system_prompt()` 为 system、
     `prompts.build_host_user_prompt` 为 user，经 `LLMClient.chat` 取「口语发言 + 指令 JSON」；
     directive 白名单 `(continue, ask_user, verdict)`；**一次格式修复 → 连续失败兜底 conclude**（F13）。
   - `build_court_interaction_card(state)`：补证卡片群内化 payload（`card_type=evidence_supplement`）。
   - `make_court_verdict_runner(...)` / `make_court_conclude_producer(...)`：verdict →
     `JudgmentReportSkill.generate_judgment` 产出书记员判决书气泡（仅 `force_stop_reason=verdict`）。
   - `build_court_wiring(...)`：一次性返回 `{host_advisor, scheduler, interaction_card, conclude_producer}`。

**M3 交付（`services/collab/graph.py`，向后兼容两注入点）**
- `build_collab_graph(...)` 增可选参 `interaction_card`（ask_user 中断 payload 模板化包装）与
  `conclude_producer`（conclude 收尾气泡后追加产出，fail-open）；**默认 None → 现有通用行为完全不变**；
- 固定边、三类护栏、白名单等一律未改；无 host/scheduler 固定出边（D14 不破）。

**M3 测试（`tests/test_collab_templates_court.py`，新，8 用例）**
- JudgeSkill collab_mode 分支（True 拼接 / 默认不变）；`court_scheduler` 交替→书记员→对辩→收敛
  与无原被告退化；补证卡片 payload；host_advisor 解析/修复/兜底（court 枚举拒绝 `conclude`）；
  conclude_producer 仅 verdict 产出；**F7 全流程**（开庭→对抗交替→补证 interrupt（卡片）→
  resume 续跑（原/被告各一次、不重复）→ verdict→判决书气泡）；**向后兼容**（默认 payload 无卡片字段）。

**自动测试**：`tests/test_collab_templates_court.py` 8 用例全绿；全量后端 **253 passed**
（基线 245 + 8，无回归）。前端本卡**零改动**。

**实施偏离（已记录）**
- **生产图全局接线曾为遗留集成项**：与 T1.6 M3 同一留项——`get_collab_graph()` 曾用默认桩，
  未接真实 `HostSkill/SchedulerSkill/AgentNodeRunner/court 适配件`；本卡的 court 适配件以
  `build_court_wiring()` 形式提供，供集成期按模板 `adapter` 组装。**该留项已于 §3.8 收口**。
- **court 指令字段不含 `next`**（承接 D14：发言顺序归 scheduler）；spec §6 的 `next/search_request`
  相应移除，与 `prompts.py` 的 host 指令 schema 保持一致。

#### 3.8 生产图全局接线交付记录（T1.7⁺ ✅）——集成收口

**目标**：把 T1.3–T1.7 一直以**默认桩**编译的 `get_collab_graph()` 换成**真实件**，
并按模板 `adapter` 分派，使**同一张星型图**既跑庭审、又跑通用会商（收口 T1.6 M3 / T1.7 的
唯一遗留集成项）。

**交付 1（`services/collab/production.py`，新）**
- `build_production_injectables(*, llm, registry, store, emit, verdict_runner)` 一次性返回
  `build_collab_graph(...)` 的 7 个可注入件（均可注入 → 单测整体替换为假件）；
- **按 `adapter` 分派**（判据 `is_court_template`，无任何图固定边）：
  - `host_advisor`：court → `build_court_host_advisor`（法官，开放 `verdict`）；其余 → `HostSkill.speak_and_decide`；
  - `scheduler`：court → `court_scheduler`（打散串行、庭审用语中性）；其余 → `SchedulerSkill.decide`（D14）；
  - `interaction_card`：court → 庭审补证卡片（同步件由分派器包成 async）；其余 → `{}`；
  - `conclude_producer`：court → verdict 判决书气泡（可注入 `verdict_runner`）；其余 → `[]`；
  - `agent_runner = make_agent_runner(...)`、`tool_runner = make_tool_runner(...)`、
    `decision_recorder = audit.record_host_decision`（fail-open）。
- 分派在**调用时**按 `state.case_type` 查模板（注册表进程级缓存）→ **同一张编译图服务所有模板**。

**交付 2（`services/collab/graph.py`，改）**
- `ask_user` 节点的 `interaction_card` 注入点**支持 awaitable**（`inspect.isawaitable`，兼容
  sync/async；默认 None 行为不变）——生产分派器为 async（需查模板）；
- `get_collab_graph()` 改为真实装配：`build_production_injectables(registry=reg)` →
  `build_collab_graph(registry=reg, **injectables)`（延迟导入避免 graph ↔ templates.court 循环依赖）。

**测试（`tests/test_collab_production.py`，新，6 用例）**：装配 7 键 + 真实绑定；
`host_advisor` 分派（court 开放 verdict / 通用修复后 conclude）；`scheduler` 分派
（court 无 LLM 点原告 / 通用走 SchedulerSkill）；`interaction_card` / `conclude_producer`
分派（court 补证卡片 + verdict 判决书；通用空产出）；**端到端**——真实分派件接入真图，
`ask_user` 中断 payload 含庭审补证卡片（异步卡片被 await），通用模板同图无 court 字段。

**自动测试**：`tests/test_collab_production.py` 6 用例全绿；全量后端 **259 passed**
（基线 253 + 6，无回归）。前端本卡**零改动**。

**说明**：分派为**数据驱动**（adapter 判据），无硬编码业务顺序；`/debate/stream` 旧链路
未触碰（A3 红线）；LLM 仍仅经内部 `get_llm_client`（LiteLLM）调用。

#### 3.9 T1.8 交付记录（M1–M4 已交付 ✅）——消息中心三栏 IA 与建群向导

**范围（D17–D19）**：旧「智能咨询」并入单聊（`direct`，走 T1.5 B1 执行层），旧「模拟法庭」
并入群聊（`group`，选案情模板 + 可扮演／可不扮演），实时体感复刻于新 collab SSE；旧
`/chat`、`/court`、`/knowledge`、`/cases`、`/dashboard` 仅从导航隐藏并加访问拦截（代码保留）。

**M1 交付（三栏 IA 外壳）**
- 新增 `app/lib/collab.ts`（会话/成员/Agent/模板类型 + `request` 解包封装）；
  `store/useCollabStore.ts`（会话列表/目录/选中态/右栏开关 + `upsertConversation`）；
- 新增 `components/collab/*`：IconRail、ConversationList（direct/group 图标、标题搜索）、
  ChatArea（会话头）、RightRail（成员只读）、Avatar、format；
- 新增 `app/messages/page.tsx` 三栏外壳，接 `GET /api/conversations`、`GET /api/agents`、
  `GET /api/agents/templates`；`components/Sidebar.tsx` 加「消息中心」入口。

**M2 交付（collab SSE 流式）**
- 新增 `app/lib/sse.ts`：票据换取（`POST …/events/ticket`）→ `EventSource`（`events_token`
  查询鉴权 + Last-Event-ID）→ 按 Stream id 去重、8 事件监听、5 次指数退避重连、`close()` 停止；
- 新增 `store/useCollabStreamStore.ts`（单激活会话流：messages/streams/phase/pending/
  turnStatus/lastEventId + `open/close/handleFrame/send/handBack/retryLast`）；
- 新增 `components/collab/ConversationView.tsx`（单聊保持简单；群聊渲染相位条 + 交互卡片）、
  MessageBubble、InteractionCard；`ChatArea` 消息区接入 `ConversationView`。

**M3 交付（建群向导）**
- `app/lib/collab.ts` 增 `CreateConversationBody` + `createConversation`（`POST /api/conversations`）；
- 新增 `components/collab/NewConversationWizard.tsx`（props `open/onClose`）：入口二选一 ——
  「单聊（选 1 个可对话 Agent → `target_agent_id`）」／「群聊（选 `template_id`）」；
  群聊二步：模板列表 → 成员确认（展示模板 roster，host 缺失时前插补位；可追加 `agent_ids`；
  选「我不扮演／我扮演某人」＝ `my_role` ∈ 最终 roster；可选标题）→ 创建；
- `app/messages/page.tsx` 用本地状态挂向导，`ConversationList` 的「+」回调打开；创建成功
  `upsertConversation` + `selectConversation` 直接进入该会话。
- **已知限制**：模板成员在创建时**只增不减**（`extra_agent_ids` 语义）；移除模板成员须建群后
  用 `DELETE /members`（M4 群管理承接）。

**验证**：`tsc --noEmit` 0 报错；`/messages` dev 编译 200（2687 modules）；curl 实测
`POST /api/conversations`（direct：`target_agent_id`；group：`template_id` + `agent_ids` +
`my_role`）均 201 且返回 conversation，host/roster 按模板铺开、`my_role` 校验通过。
旧链路（`/chat`、`/court`、`/debate/stream`）**零改动**。

**M4 交付（接管角标/交还、右栏群管理 + Agent 时间线、纪要卡、回到此轮）**
- 后端：`routers/conversations.py` 新增 `SetMyRoleRequest` + `POST /{id}/my_role`
  （仅群聊；非空须 ∈ 成员；空＝不扮演＝交还给 AI；返回最新 conversation，跨轮持久化，收口 §3.6 M2 留项）。
- `app/lib/collab.ts`：新增 `setMyRole` / `addMember` / `removeMember`（对应 `my_role`、`members` 增删端点）。
- `store/useCollabStreamStore.ts`：新增 `turnId`，由 `send` 的 `res.turn_id` 与
  `status/interaction_required/done` 帧写入，供右栏 checkpoint 定位当前轮。
- `components/collab/ConversationView.tsx`：群聊顶部「你正在扮演「XX」／交还给 AI」琥珀色角标；
  `handleReleaseRole`——接管暂停中走 `handBack()`，否则 `setMyRole(id,null)` + 刷新会话；持久消息透传 `msgType`。
- `components/collab/MessageBubble.tsx`：新增 `msgType` 分支（`minutes`＝会商纪要卡、`card`＝会商卡片，蓝边卡样式）。
- `components/collab/RightRail.tsx`：整体重写为**群管理 + Agent 时间线**——成员增删（非 host 且非本人扮演者可移除）、
  可追加 Agent，及 `listCheckpoints(id, turnId)` 时间线（第 N 轮/步骤、`directive`、host `reason`、
  `force_stop_reason`、`spoken`、`is_latest`），非最新项「回到此轮」按钮触发 `forkTurn`。

**验证**：`tsc --noEmit` 0 报错；`test_conversations_api.py` 18 用例全绿（16 + 新增 2）；
全量后端 **261 passed**（基线 259 + 2，无回归）；重启后端 curl 冒烟——建 court 群（roster
judge/plaintiff_lawyer/defense_lawyer/clerk）、`my_role`=成员（200，回写 `plaintiff_lawyer`）、
`my_role`=null（200，清空）、`my_role`=ghost（40001）、direct 群校验（40001）、成员增删（200）均符合预期。
旧链路（`/chat`、`/court`、`/debate/stream`）**零改动**。

**T1.8 全文完成**：M1（三栏 IA 外壳）、M2（collab SSE 流式）、M3（建群向导）、M4（接管角标/交还、右栏群管理 +
Agent 时间线、纪要卡、回到此轮）均已交付。

**T1.9 全文完成**：M1（「结束会商」用户主权 / 注入 conclude，验收 F6，详见 §3.10）✅；
M2（会商纪要生成、`POST /{id}/minutes`、`msg_type=minutes`，详见 §3.11）✅；
M3（法规/类案引用卡 → `msg_type=card`，详见 §3.12）✅。

### 3.10 T1.9 交付记录（M1 已交付 ✅）——「结束会商」用户主权（注入 conclude）

**验收 F6**：「结束会商」立即收尾；会商进行中再发消息返回 50901；用户按钮经由图注入 conclude
（`collab-supervisor-checkpoint_spec.md` §F6 原述为 `Command(update/goto)`，落地实现对等）。

**M1 交付（结束会商按钮 + conclude 注入）**
- 后端 [graph.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/graph.py)：
  新增 `_is_conclude(resume_value)` 判据（兼容 `{"action":"conclude"}` / `{"conclude":true}`）；
  `ask_user_node` 与接管 agent 节点（`my_role` 命中）在 resume 值为 conclude 时返回普通 dict
  `{"force_stop_reason": "user_conclude"}`，经**唯一固定回边**到 `host`；
  `host_node` 开头新增早退守卫——`force_stop_reason == "user_conclude"` 时**不调 LLM**，
  直接 `Command(goto=CONCLUDE_NODE, update={})`，与既有 verdict/max_rounds/budget 收尾路径合一。
  - **关键坑（实测）**：带**静态出边**的节点（`ask_user → host`、`agent__* → host`）返回
    `Command(goto=...)` **不会覆盖静态边**（resume 后仍走回 host 再次中断）；而
    `Command(resume=..., goto=...)` 会触发 `InvalidUpdateError: At key 'force_stop_reason':
    Can receive only one value per step`。故采用「中断节点只写标记 → host（无静态出边、本就
    返回 Command）注入 goto」的等价方案。
- 后端 [conversations.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/conversations.py)：
  `SendMessageRequest` 空 content 放行新增 `metadata.conclude` 判据（与 `hand_back` 并列）；
  挂起轮次（`TURN_INTERRUPTED`）时 `_resume_message(..., conclude=True)` →
  `runner.resume_turn(turn_id, {"action": "conclude"})`，返回 `{message:null, status:completed}`「已结束会商」；
  **无挂起轮次**时 conclude 直接 `40001 当前没有进行中的会商，无法结束`。
- 前端 [useCollabStreamStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useCollabStreamStore.ts)：
  新增 `conclude()` action（空 content + `metadata.conclude`；控制动作不落聊天气泡，成功后清空 pending）。
- 前端 [InteractionCard.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/InteractionCard.tsx)：
  新增 `onConclude?` prop 与 `Flag` 图标「结束会商」按钮（takeover 与非 takeover 两分支均渲染）。
- 前端 [ConversationView.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/ConversationView.tsx)：
  接线 `onConclude={() => void conclude()}`。

**验证**：`tests/test_collab_graph.py` **13 passed**（新增 2 用例 `test_ask_user_resume_conclude_injects_goto`
/ `test_takeover_resume_conclude_injects_goto`：resume conclude 后**不再中断**且 `force_stop_reason
== "user_conclude"`）；全量后端 **263 passed**（基线 261 + 2，无回归）；前端 `tsc --noEmit` **0 报错**；
重启后端 curl 端到端冒烟——court 群（`my_role=plaintiff_lawyer`）发消息 → `status=interrupted`，
再发 `{content:"", metadata:{conclude:true}}` → `201 status=completed`，checkpoint 复现
`force_stop_reason=user_conclude`，无挂起轮次再发 conclude → `40001`。旧链路（`/chat`、`/court`、
`/debate/stream`）**零改动**。

### 3.11 T1.9 交付记录（M2 已交付 ✅）——会商纪要生成（`msg_type=minutes`）

**范围**：用户点「生成会商纪要」→ 书记员（`clerk`）汇总本会话各方观点，产出 Markdown《会商纪要》，
token 级流式推送并以 `msg_type=minutes` 落库；同一轮次幂等复用。
（「每 3 轮自动一次」的 conclude 自动产出于本轮**暂缓**——避免无成本门控的自动生成拖慢「结束会商立即
收尾」，以**手动按钮**为主触发，符合 spec 主路径。）

**M2 交付（会商纪要生成）**
- 后端 [minutes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/minutes.py)（新）：
  `MinutesRunner`（`llm/store/registry/emit/model` 全可注入）、`build_minutes_material(conv, messages)`
  与会话记录拼装、`MINUTES_SYSTEM_PROMPT`（约定 Markdown 结构：会商议题 / 各方观点 / 争议焦点 /
  结论与建议 / 待办事项）。
  - **S1 流式**：`status{phase:minutes}` → `message_start{type:minutes}` → 多帧 `message_delta`
    → `message_end{content, metadata:{msg_type:minutes}}`，复用 `agent_nodes` 的同名事件常量与
    `_default_emit`（协议一致）。
  - **幂等**：`event_key = {conversation_id}:minutes:r{round}`、`message_id = uuid5(event_key)`；
    「先查库后发」——同轮次纪要已存在直接 `reused=true` 复用，不重复生成/推送；落库走
    `insert_message_once(... ON CONFLICT (event_key) DO NOTHING)`，被幂等挡住时回取既有记录。
  - `round_no` 缺省取历史消息 `max(round)`；空记录抛 `40001 暂无可整理的会商记录`。
  - 单例 `get_minutes_runner()` / `reset_minutes_runner()`（测试可 override 注入假 runner）。
- 后端 [conversations.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/conversations.py)：
  新增依赖 `get_minutes_runner()` 与 `POST /api/conversations/{conversation_id}/minutes`（`201`），
  返回 `{message, event_id, reused}`。
- 前端 [collab.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/collab.ts)：
  `MinutesResult` 类型 + `generateMinutes(conversationId)`。
- 前端 [useCollabStreamStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useCollabStreamStore.ts)：
  新增 `generateMinutes()` action（成功后按 id 去重并入 `messages`）。
- 前端 [RightRail.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/RightRail.tsx)：
  群聊时成员区下方新增「生成会商纪要」按钮（`FileText` 图标 + `minutesBusy` 态）。
  `msg_type=minutes` 的渲染复用 M4 已交付的 [MessageBubble.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/MessageBubble.tsx) 纪要卡分支。

**验证**：`tests/test_collab_minutes.py`（新，**7 passed**：材料标签 / S1 事件序列 / 幂等复用 /
round 缺省 / 空记录 40001 / emit fail-open / 历史条数）；`tests/test_conversations_api.py`
（+2 用例，**20 passed**：端点 201 与 404）；全量后端 **272 passed**（基线 263 + 9，无回归）；
前端 `tsc --noEmit` **0 报错**；重启后端 curl 端到端冒烟——court 群发消息（原告/被告律师 r1/r2 发言）
→ `POST /{id}/minutes` **201**，`msg_type=minutes`、`content 1465 字`、`reused=false`，二次调用
`reused=true`（幂等）。旧链路（`/chat`、`/court`、`/debate/stream`）**零改动**。

### 3.12 T1.9 交付记录（M3 已交付 ✅）——法规/类案引用卡（tool 检索结果 → `msg_type=card`）

**范围**：工具辐条（法规检索员 / 类案检索员）检索前后发 `tool` 进度事件；有结果时产出结构化
「法规引用卡 / 类案引用卡」并幂等落库（`msg_type=card`）+ 下发 `message` 事件。
（对齐 [collab-ui-refactor_plan.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-ui-refactor_plan.md)
§5.3⑤ / §5.5：`tool` 事件 `status/query/result_count/elapsed_ms`，`message` 事件携带 `msg_type=card`。）

**M3 交付（引用卡）**
- 后端 [tool_nodes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/tool_nodes.py)：
  `ToolNodeRunner` 新增可注入 `store` / `emit`：
  - **进度事件**：检索前发 `tool{status:running}`，成功后发 `tool{status:done, result_count, elapsed_ms}`，
    异常发 `tool{status:error}`（fail-open，仍返回空结果、不产出卡）；
  - **引用卡**：有结果且处于轮次内时，产出 `msg_type=card`（结构化 `metadata.citations` +
    领域中文标签正文），`event_key={turn_id}:r{round}:{tool_id}:0`、`message_id=uuid5(event_key)`，
    「先查库后发」幂等复用；落库后下发 `message` 事件（前端按 `msg_type` 渲染蓝边卡）。
  - 领域映射：`RegulatoryResearcher`→`law`/`law_citation`、`CaseSearchSkill`→`judge`/`case_citation`。
- 后端 [production.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/production.py)：
  `make_tool_runner(llm=llm, store=store, emit=emit)` —— 生产装配把 store/emit 接进工具辐条。
- **DB 约束修复**：[04-app-schema.sql](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/sql/init/04-app-schema.sql)
  `messages.sender_type` 原为 `('user','agent','system')`，**不含 `tool`**（此前工具辐条从不落库故未暴露）；
  已扩为 `('user','agent','tool','system')`，并对线上库执行 `ALTER TABLE messages ... ADD CONSTRAINT`。
- 前端 [useCollabStreamStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useCollabStreamStore.ts)：
  新增 `toolRuns: ToolRun[]` 与 `tool` 事件分支（按 `agent_id` upsert；`open/close/done` 清空）。
- 前端 [ConversationView.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/ConversationView.tsx)：
  群聊渲染工具进度行（🔍「正在检索『…』…」/「检索到 N 条法规」/「检索失败，已跳过」），
  并向 `MessageBubble` 透传 `metadata`。
- 前端 [MessageBubble.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/MessageBubble.tsx)：
  `card` 分支识别 `metadata.card_type ∈ {law_citation, case_citation}` → 渲染来源列表
  （`source` + 摘要 + 置信度）；否则沿用通用卡片正文。

**验证**：`tests/test_collab_tool_nodes.py`（新，**7 passed**：进度事件序列 / 引用卡落库 + message 事件 /
`law`&`judge` 领域映射 / 幂等复用 / 无 domain·query 不发事件 / 检索异常 fail-open / 工厂类型）；
`tests/test_collab_agent_nodes.py` 既有工具用例改注入假 store/emit（不再触真库）；全量后端 **279 passed**
（基线 272 + 7，无回归）；前端 `tsc --noEmit` **0 报错**。
**集成验证（真实 store + Redis，仅打桩检索）**：落库 `msg_type=card`、`sender_type=tool`、
`card_type=law_citation`、`citations=2`；Redis Stream 依次出现 `tool`(running)`/`tool`(done)`/`message`。
**已推翻的原结论**：曾把 API 冒烟未产出卡记为「非确定性派发（非 M3 缺陷）」。经排查**该结论错误** ——
真实根因是**结构性缺陷**（无轮首预取 + Dense 召回恒 0 条），详见 §3.13 修复记录。
旧链路（`/chat`、`/court`、`/debate/stream`）**零改动**。

**T1.9 全部里程碑（M1–M3）已交付。**

### 3.13 T1.9 修复记录 ✅ —— 工具辐条未被派发（真因：无轮首预取 + Dense 召回恒 0）

**现象**：API 冒烟（`contract` 模板群）中工具辐条（法规检索员）无 `tool` 进度事件、无引用卡。

**根因（两处结构性缺陷，均非 LLM 非确定性）**：
1. **缺「轮首并行预取」**（`collab-scheduling_spec.md` 第 70/100/113 行明确要求）：工具型 Agent
   （`is_tool=true`）**不占主串行发言位**，应由编排器在**轮首并行预取**（发 `tool` 事件、结果入共享上下文）。
   实现中从未预取，仅把工具 Agent 混入 scheduler 候选；而 `contract` 模板 `max_rounds=2` + scheduler
   「保序不跳人」约束，使 order=3 的检索员**永远轮不到** → 从未触发检索。
2. **Dense 召回恒为 0 条**：`build_sparse_conditions` 给 Qdrant 附加 `payload.domain=<domain>` 过滤，
   但库内 payload **并无 `domain` 字段**（实测 `law_knowledge` 键为 `law_id/title/type/office/status/
   publish_date/source/imported_at`，文章级含 `law_name/article_number/content/split_type`）→ 过滤命中 0 条，
   被迫每次回退关键词检索（`_keyword_fallback` 对整句 `ilike` 亦为 0）→ 结果空 → 不产出卡。

**修复**：
- [graph.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/graph.py)
  `prepare_node`：新增**轮首并行预取** —— `roster ∩ tool_ids` 去重后 `asyncio.gather` 并行调用 `tool_runner`，
  结果并入 `state["retrieved"]`（工具 Agent 非群成员则不预取）。→ 工具辐条恢复派发：
  `tool`(running/done) 事件 + 引用卡（`event_key={turn_id}:r0:{tool_id}:0`）。
- [sparse_retriever.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/sparse_retriever.py)
  `build_sparse_conditions`：**移除** `payload_filter["domain"]`（collection 已按 domain 路由，无需再过滤）
  → Dense 召回恢复（实测本查询候选 **0 → 14 条**）。

**验证**：新增 `tests/test_sparse_retriever.py`（3 用例，锁定「不得附加 domain 过滤」回归）；
`tests/test_collab_graph.py` +2 用例（轮首预取 / 非群成员不预取）；全量后端 **284 passed**，无回归。
重启后端 curl 端到端冒烟（`contract` 模板群）→ `msgs=3 card=1 types=['user','tool','agent']`；
落库 `sender_type=tool`、`msg_type=card`、`card_type=law_citation`、`event_key={turn_id}:r0:legal_researcher:0`；
卡正文含真实法条「最高人民法院关于审理劳动争议案件适用法律若干问题的解释（四）」。旧链路零改动。

**修复记录（引用卡折叠，本轮已修）**：
- **根因（两处，均致候选被折叠为 1 条）**：
  1. Qdrant 命中仅把正文放在 `payload`（`content`/`facts_summary`/`title` 等），**未提升到顶层 `content`**；
     `legal_filter` 按 `content[:120]` 去重 → 正文为空 → 全部候选视为重复 → 折叠。
  2. `merge_dense_sparse_scores` 以**原始** Qdrant 命中为基重建候选，**丢弃**了已提升的顶层 `content`。
- **修复**：
  - [rag_retriever.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/rag_retriever.py)
    新增 `_resolve_payload_content(payload)`（按 `content`→`facts_summary`→`judgment_reasoning`→`title` 回退解析正文）；
    `_deduplicate_candidates` 的 Qdrant 分支提升顶层 `content`；`_format_final_results` 同源取正文并补 `payload.title` 作 source 回退。
  - [sparse_retriever.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/sparse_retriever.py)
    `merge_dense_sparse_scores` 改为**以 `sparse_results`（字段更完整，含顶层 `content`）为基**，仅从 `dense_map` 取 dense 分数合成。
- **验证**：新增 `tests/test_rag_retriever.py`（4 用例：顶层正文提升 / distinct 候选不被折叠 / 正文回退链 / 合并保 `content`）；
  全量后端 **288 passed**（284 + 4，无回归）。in-process `retrieve_legal_knowledge` 实测
  `Stage4 法律规则过滤完成: 20 → 5 条`（was `20 → 1`）。**API 端到端冒烟**（`contract` 模板群）落库引用卡
  `sender_type=tool`、`msg_type=card`、`card_type=law_citation`、`citations=5`（第六条/第七条/第八条/第九条 +
  解释（一）第四十条…，均为真实法条），`event_key={turn_id}:r0:legal_researcher:0`（幂等）。

**遗留（已知、未在本轮修）**：
- ~~`judge` 域 Dense 分数约 0.44–0.49，低于 `SCORE_THRESHOLD_DENSE=0.55` → 类案工具恒 0 条~~
  **经复测：该结论不成立，非缺陷**。`judge_knowledge` 有 **50317 点**（数据在库）；**域内查询**
  （如「武某合同诈骗案的裁判要旨与量刑」）Dense 头部 **0.65–0.71**，100 条 ≥0.55 → `retrieve_legal_knowledge(domain="judge")`
  正常产出 **5 条类案**（均为合同诈骗/诈骗案）。此前观测到的 0.44–0.49 是**用「劳动争议」查询去打 judge 语料**
  造成的跨域低相似 —— 此时返回 **0 条恰是正确行为**（强把阈值放宽到 0.40 只会引入**与劳资问题无关的刑案**）。
  **故不动阈值**；`law` 侧行为不变（0.55，头部 0.80）。
- `_keyword_fallback` 以整句 `ilike` 检索，命中为空时返回 `[]`（无占位兜底）。
- （新发现·环境侧）**`Qwen/Qwen3-Reranker` 本地未落地**：`rerank_documents` 每次触发 HuggingFace
  网络重试（约 **2 分钟**、5 次）后才回退，且回退后全体候选 `rerank_score=0.5` → Stage3/Stage4 排序退化为
  **仅按法源权重**。这也是此前 API 冒烟单请求耗时 ~152s 的主因。建议后续补下载模型或把 `RERANKER_MODEL` 指向本地路径。

---

### 3.14 T2.1 交付记录 ✅ —— 长期记忆（PG 权威 + Qdrant 向量）与 memories CRUD API

**范围**：Qdrant 新增 `user_memories` 集合（1024/Cosine）+ 用户记忆 CRUD（增删改查、type/scope/case/q 过滤、
按 user 隔离）+ 自动记忆总开关（按用户隔离）。

**改动文件**：
- [qdrant_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/qdrant_client.py)
  新增 `COLLECTION_USER_MEMORIES = "user_memories"`，`init_qdrant()` 的 `collection_defs` 追加该项；
  集合存在性判定改用 `await client.collection_exists(name)`（**本地模式缺失集合抛 `ValueError`、远程模式抛
  `UnexpectedResponse`**，用 `get_collection` 吞异常不可靠 → 统一判定后创建）。
- [services/memory/store.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/memory/store.py)（新）
  `MemoryStore`：PG `memories` 为权威（每方法短事务），Qdrant `user_memories` 为向量；
  `list/get/create/update/delete` 一律带 `user_id` 过滤；`_index/_unindex` 尽力而为（嵌入或向量库失败仅回写
  `embedding_status=failed`，**不阻断 CRUD**）；`is_memory_enabled/set_memory_enabled`（Redis 键
  `legalmind:memory:enabled:{user_id}`，缺省开、Redis 异常按开降级）。
- [services/memory/\_\_init\_\_.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/memory/__init__.py)（新）
- [routers/memory.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/memory.py)（新）
  `EnvelopeRouter(prefix="/api/memories")`：`GET/PUT /setting`（**须先于 `/{memory_id}` 声明**）、
  `GET ""`（scope/memory_type/case_id/status/q/limit/offset）、`POST ""`(201)、`GET/PATCH/DELETE /{memory_id}`；
  非法 scope/status → `InvalidParamsError`，不存在 → `NotFoundError`。
- [main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py)
  导入并 `app.include_router(memory.router)`（并入 Harness 信封）。

**验证**：
- 新增 `tests/test_memory_api.py`（4 用例：CRUD 往返 / **按 user 隔离** / 过滤+参数校验 / 总开关），
  全量后端 **292 passed**（288 + 4，无回归）。
- 重启后端：`Collection 'user_memories' 创建成功`、`Qdrant 初始化成功`、`/readyz` 200。
- curl 端到端冒烟：`GET/PUT /setting` 开关往返正确；`POST` 记忆 → `embedding_status=done`（向量已入库）；
  `GET` list/单条、`PATCH`、`q=合同` 过滤命中、`scope=bad`→`40001`、`DELETE`→ 再取 `40404` 均符合预期；
  另注册 `smoketest1` 验证跨用户 `list total=0`（隔离生效）。冒烟数据已清理。

### 3.15 T2.2 交付记录 ✅ —— 记忆写入管线（turn 结束派发 → Flash 抽取 → 相似度三重判定 → PG+向量）

**范围**：轮次成功收尾后自动派发记忆事件 → 抽取本轮对话中的用户画像候选 → 与已有记忆做向量相似度
比对（≥0.90 合并 / 0.75–0.90 去重提示 / <0.75 新增）→ PG upsert + Qdrant 重嵌入；失败重试达上限进 DLQ。

**改动文件**：
- [core/config.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/config.py)
  新增 `KAFKA_TOPIC_MEMORY_DLQ`，以及 `MEMORY_EXTRACT_MODEL / MEMORY_MERGE_THRESHOLD(0.90) /
  MEMORY_DEDUP_THRESHOLD(0.75) / MEMORY_MAX_ATTEMPTS(3) / MEMORY_TURN_MESSAGES_LIMIT(40) / MEMORY_RETRY_BACKOFF`。
- [core/metrics.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/metrics.py)
  新增 `MEMORY_INGEST{result}`（ok/skipped/dlq/error）与 `MEMORY_EXTRACT{action}`（merge/prompt/new）。
- [services/memory/extractor.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/memory/extractor.py)（新）
  Flash 抽取器：`EXTRACT_SYSTEM_PROMPT`（只抽用户本人 fact/preference/background/demand/timeline、自足第三人称、
  禁编造、importance 1-5）+ `parse_candidates`（去围栏/正则取 JSON、非法枚举归位、按内容去重、截断至 8 条、
  整体失败返回 `[]`）。
- [services/memory/pipeline.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/memory/pipeline.py)（新）
  写入管线：`load_turn_transcript`（自 `trigger_message_id` 起取本轮消息）→ `_apply_candidate`（嵌入 → `store.similar`
  取 top5 → 三重判定）→ `ingest_turn`（turn 不存在/开关关闭/无消息 → skipped）→ `dispatch_memory_event`
  （`ENABLE_KAFKA` 时发 `memory-events`，否则进程内 `asyncio.ensure_future` 降级，全程 fail-open）。
- [worker/consumers/memory.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/worker/consumers/memory.py)（新）
  `memory-events` 消费器：逐条 `ingest_turn`，失败按 `MEMORY_MAX_ATTEMPTS` 指数退避重试，**耗尽 → 发 `memory-events-dlq` + ack**
  （毒消息不阻塞队列）；broker 不可达退化为仅心跳。
- [worker/main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/worker/main.py)
  `--role memory` 接入 `consume_memory_events`；`collab` 角色构建 runner 时注入 `memory_dispatch`。
- [services/collab/runner.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/runner.py)
  `TurnRunner` 新增注入式钩子 `memory_dispatch`（**默认 None**）→ `_on_success` 收尾后 `await self._dispatch_memory(turn)`；
  `make_turn_runner`/`get_turn_runner` 透传，默认实现惰性 import `dispatch_memory_event`。异常仅告警，**绝不改轮次终态**。

**关键设计取舍**：
- **零侵入钩子**：`memory_dispatch` 默认 `None` → 未注入时行为与旧实现完全一致，现有 runner 测试无需改动用例参数。
- **「0.75–0.90 去重提示」**：当前无 UI/事件通道，故实现为「**照常新增记忆** + 告警日志 + 返回
  `similar_memory_id/score` + `MEMORY_EXTRACT{action="prompt"}` 指标」，既不静默合并也不丢候选；
  前端提示通道留待 T2.4 记忆页落地。

**验证**：
- 新增 `tests/test_memory_worker.py`（11 用例：解析容错 / 三重去重动作 / 消费器重试-DLQ / Kafka 关闭进程内派发），
  `tests/test_collab_runner.py` +2（派发被调用 / 派发失败 fail-open）；全量后端 **305 passed**（292 + 13，无回归）。
- **现场探针**（真实 PG + 真实 Qdrant，LLM 用假件注入，不依赖 LiteLLM）：两轮对话同候选 →
  第 1 轮 `action=new`、第 2 轮 `action=merge`（score 1.0000）→ PG `total=1`（成功合并）、`embedding_status=done`、
  Qdrant 以同文本召回自身 score 1.0000。探针数据已自清理。
- 重启后端：Qdrant 初始化成功、`/readyz` 200。

### 3.16 隐藏主持人 Agent + 轮次发言分隔条 交付记录 ✅

**范围**：主持人（host/scheduler）决定发言顺序与是否续轮，但**对用户完全不可见**；用户只看到
无背景、小字居中的中性分隔条「下面是 X 发言」（随轮次幂等落库、刷新仍在）。最终判决由法官给出，
调解员出场与否由主持人依上下文决定。

**改动文件**：
- [services/collab/speaker_notice.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/speaker_notice.py)（新）
  `make_speaker_notice`：`sender_type=system` / `msg_type=notice`，`event_key={turn}:r{round}:notice:0`
  （第 3 段用 `notice`，避开 Agent 流式的 `agent_id`），`message_id=uuid5(event_key)`，
  「先查库后发」幂等 + 热缓存 + `message` 事件；`metadata.kind="speaker_notice"` 供前端区分；全程 fail-open。
- [services/collab/graph.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/graph.py)
  新增 `SpeakerNotice` 注入点与 `build_collab_graph(speaker_notice=...)`；`scheduler_node` 在定出
  `next_speaker` 后、`update["round"]` 前调用（单聊 direct 不经 scheduler → 无分隔条）。
- [services/collab/production.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/production.py)
  返回 dict 增加 `speaker_notice`。
- [components/collab/MessageBubble.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/MessageBubble.tsx)
  新增 `notice + metadata.kind=speaker_notice` 分支（无背景/小字居中）；删除 `isHost` 与「主持人」amber chip。
- [components/collab/RightRail.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/RightRail.tsx)
  「Agent 时间线」→「本轮发言顺序」；删 host 皇冠；去「指令/理由」原始文案（`reason` 可能含「主持人」），
  改为中性中文映射（本轮/提前结束）。
- [components/collab/NewConversationWizard.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/NewConversationWizard.tsx)
  删除成员列表的 host 皇冠（保留建群所需 `role` 数据）。

**关键设计取舍**：
- **主持人本就不可见**：host 口语发言只写 `state["messages"]`（不落库）→ 聊天区无 host 气泡；
  本次仅清理前端残留文案/角标，并补一条中性分隔条。
- **无 DB 迁移**：沿用既有 `sender_type=system` + `msg_type=notice` 合法组合（见 `routers/conversations._append_notice`），
  以 `metadata.kind` 区分轮次分隔条与成员变动通知。

**验证**：
- 新增 `tests/test_speaker_notice.py`（8 用例：产出/中立性/幂等/uuid5/降级/边界 + 图级触发/未注入不产出），
  `tests/test_collab_production.py` 契约键补 `speaker_notice`；全量后端 **324 passed**（316 + 8，无回归）。

### 3.17 联网检索（DeepSeek Search/Fetch）交付记录 ✅

**范围**：发言 Agent 在**正式流式发言前**自主判断是否需要联网，需要则检索外部公开信息
（最新法规/司法解释/新闻/公开资料），以**引用卡 + 资料块**形式并入上下文；密钥仅经
LiteLLM 透传注入，后端不接触真实 key。

**Step1（客户端 + 透传 + 单测）✅**
- [core/web_search.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/web_search.py)（新）：
  `WebSearchClient.search_web()/fetch_url()`，**透传优先 + 直连回退**双链路，可重试错误
  （408/429/5xx/超时）按 `WEB_SEARCH_MAX_ATTEMPTS` 退避；`normalize_search_result`
  按 `content→summary→snippet` 回退；`WebSearchError`。
- `core/config.py` 新增 `WEB_SEARCH_*`（ENABLED/COUNT/TOP_N/TIMEOUT/MAX_ATTEMPTS/NEED_CONTENT），
  `core/metrics.py` 新增 `legalmind_web_search_calls_total{op,mode,status}`，
  `litellm/config.yaml` 新增 `/v1/tools/search|fetch` 透传端点（`Bearer os.environ/DEEPSEEK_API_KEY`）。
- `tests/test_web_search.py`（11 用例，httpx.MockTransport）。

**Step2（发言前置决策 + 引用卡 + 资料块 + 单测）✅**
- [services/collab/web_decision.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/web_decision.py)（新）：
  `make_web_context` → `WebContextProvider.maybe_search(agent, state, ctx, conversation_id)`：
  用**该 Agent 自己的模型** + `web_search`/`web_fetch` function schema 做前置决策；
  需要则检索 → 发 `tool` 进度事件（running/done/error）→ 产出 `msg_type=card`
  联网引用卡（`card_type="web_citation"`，`event_key={turn}:r{round}:{agent}:web` 幂等落库
  + 热缓存 + `message` 事件）→ 返回 `【联网检索资料】` 资料块。
- [services/collab/agent_nodes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/agent_nodes.py)：
  `AgentNodeRunner` 新增 `web` 注入点，在构建 `ctx` 后、流式发言前把资料块并入 `ctx.materials`
  （**零侵入**：不改任何 Skill 流式方法）。
- `services/collab/production.py`：`make_agent_runner(..., web=make_web_context(...))`。
- 前端 [MessageBubble.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/MessageBubble.tsx)：
  引用卡支持 `card_type="web_citation"`（标题「联网检索」）并渲染来源链接。

**关键设计取舍**：
- **开关与降级**：`WEB_SEARCH_ENABLED=False` → 零额外 LLM/网络调用；决策/检索任何异常
  只记日志 + 发 `tool:error`，**返回空串不阻断发言**（对齐 A1「代码只做护栏」）。
- **零侵入**：联网资料只并入既有 `ctx.materials`（Skill 早已消费该字段），不新增图节点/固定边。
- **键隔离**：联网卡 `...:{agent}:web` 与 Agent 正文 `...:{agent}:0`、法规/类案工具卡
  `...:{tool_id}:0`、分隔条 `...:notice:0` 互不冲突。

**验证**：`tests/test_web_decision.py`（10 用例：开关/决策/搜索/抓取/幂等/两级降级 +
AgentNodeRunner 并入资料块/未注入行为不变）；全量后端 **334 passed**（324 + 10，无回归）。

**Step3（现场验证）✅**
- Search：`client.search_web("最新彩礼返还司法解释", top_n=3)` 真实返回 **3 条**公开结果
  （湖南高院涉彩礼典型案例、涉彩礼纠纷司法解释等），含 `title/url/content/site_name`；
- Fetch：`client.fetch_url(<真实法条页>)` 真实返回 `title` + 正文 **5744 字符**；
- 本机未起 LiteLLM、`LITELLM_VIRTUAL_KEY` 为空 → `_use_proxy=False`，
  自动走**直连回退**链路（`_use_direct=True`）即成功，验证「透传优先 + 直连回退」双链路成立。
- 验证脚本为一次性临时件，跑完即删（未入库、未落盘密钥）。

**遗留**：无。

### 3.18 T2.3 交付记录 ✅ —— 对话链路 prepare 节点长期记忆召回

**范围**：`prepare` 节点在正式编排前按**语义**召回该用户 top5 长期记忆，注入群上下文
**独立块**（`【已召回的用户背景记忆】`，**不覆盖任何 Skill 人设 prompt**），并下发
`memory_recall` 工具进度事件；用户关闭总开关即**不读不写**。

**实现**：
- `services/collab/memory_recall.py`（新）：`MemoryRecallProvider` + `make_memory_recall(...)`，
  零侵入范式对齐 `web_decision.make_web_context`。`recall(state)`：开关关/无 `user_id`/无本轮问题
  → 直接空（不读）；`is_memory_enabled` 为 False → 不读；否则 `embed_text(question)` →
  `MemoryStore.similar(user_id, top_k=5)` → 回 PG 逐条补水 `content` 并按 `status=active` 过滤 →
  发 `memory_recall` 工具事件（`running`/`done`/`error` + `result_count`/`elapsed_ms`）；
  异常 fail-open 返回空，绝不阻断本轮。
- `state.py`：`CollabState` 增 `user_id`；`initial_state` 增 `user_id` 入参。
  `runner._initial_state` 传 `turn.get("user_id")`。
- `graph.py`：`build_collab_graph` 增 `memory_recall` 注入点（默认 `None` → 行为不变）；
  `prepare_node` 先召回（direct/group 均执行）再走原有工具辐条预取。
- `production.py`：`build_production_injectables` 增 `"memory_recall": make_memory_recall(emit=emit)`。
- `core/config.py`：新增 `MEMORY_RECALL_TOP_K=5`、`MEMORY_RECALL_MIN_SCORE=0.0`。
- 前端 `components/collab/ConversationView.tsx`：工具进度文案新增 `memory_recall → '记忆'`
  （前端 `tool` 事件要求 `agent_id` 非空，故用 `agent_id="memory_recall"`）。

**关键设计取舍**：
- **零侵入**：不改任何 Skill 人设 prompt 与流式方法；召回结果只填既有 `state["memories"]` 字段，
  由既有 `build_group_context` 渲染为独立块。
- **不读不写一致**：读侧（本条）与写侧（T2.2 `pipeline._ingest`）**共用** `is_memory_enabled`，
  关开关后两侧同时生效。
- **fail-open**：嵌入/向量库/PG/事件任一异常仅告警 + `tool:error`，返回空记忆，不阻断编排。

**验证**：`tests/test_memory_recall.py`（10 用例：总开关关/用户关零读零事件、无 user_id/无问题短路、
正常召回补水 + running/done + `result_count`、已删除/非 active 过滤、`similar`/`embed` 抛错 fail-open、
事件推送失败不影响召回）；`tests/test_collab_graph.py` +2（prepare 接线：注入件调用一次且落
`state.memories`、召回件抬异常 fail-open 不阻断）；`tests/test_collab_production.py` 注入件键集合同步更新；
全量后端 **346 passed**（334 + 12，无回归）。

**遗留**：无（0.75–0.90 去重提示的前端通道仍留待 T2.4 记忆页）。

### 3.19 T2.4 交付记录 ✅ —— 前端记忆页 + 案件视图

**范围**：新增独立「记忆」模块页 `/memory`（分类 Tab / 星标置顶 / 来源跳转 / 编辑 / 删除 /
手动新增 / 召回总开关），并以 `?view=cases` 提供「案件视图」替代旧 `/cases`。

**实现**：
- **后端补 `starred` 字段**（此前设计仅「置顶」无字段，T2.4 落地为布尔列）：
  `sql/init/04-app-schema.sql` `memories` 增 `starred BOOLEAN NOT NULL DEFAULT false`
  （含 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 幂等迁移）；`core/pg_client.Memory` 同步列；
  `services/memory/store.py`：`_to_dict` 输出 `starred`，`list()` 支持 `starred` 过滤且
  排序改为 `starred DESC, updated_at DESC`（实现「置顶」），`create/update` 接收 `starred`；
  `routers/memory.py`：Create/Update 请求体与 list 查询参数全部透传 `starred`。
- 前端数据层 `app/lib/memory.ts`（新）：对齐 `/api/memories` 全部端点（list/get/create/update/
  delete/setting），导出 `MemoryRecord` 类型、`MEMORY_TYPE_TABS` 分类映射
  （background→用户画像 / fact→案件事实 / demand→诉求与底线 / timeline→时间节点 /
  preference→策略偏好）与 `memoryTypeLabel`。
- 状态层 `store/useMemoryStore.ts`（新）：列表 + 过滤（分类/星标/归档/搜索）+ 选中项 + 总开关；
  `toggleStar` 走 PATCH 后重拉以刷新置顶排序。
- 组件 `components/memory/`（新）：
  - `MemoryList`：分类 Tab、星标/归档过滤、搜索、召回总开关、手动新增入口；
  - `MemoryDetail`：内容/摘要/重要性星级/来源跳转（`source_conversation_id` → `/messages` 选中会话）/
    编辑/归档/删除/星标；
  - `MemoryEditor`：新增与编辑共用弹窗（分类/内容/摘要/重要性/星标）；
  - `CasesPane`：「案件视图」= 协同群聊（`GET /api/conversations` type=group）+ 合同审查记录
    （本地按用户名隔离键 `legalmind_contract_reviews:{username}`），列表 + 详情两列，
    群聊可「进入会话」、合同可「查看审查」。
- 页面 `app/memory/page.tsx`（新）：三栏 `IconRail | 列表 | 详情`，`?view=cases` 时切换 `CasesPane`；
  `useSearchParams` 以 `Suspense` 包裹。
- 导航与路由：`components/collab/IconRail.tsx` 增「记忆」图标入口（`/memory`）；
  `components/AuthGuard.tsx` 将 `/cases` 从「并入消息中心」集合移出，改为重定向
  `/memory?view=cases`。

**关键设计取舍**：
- **星标即后端字段**（用户拍板）：跨设备持久，与「PG 为权威源」约定一致；不再用 localStorage 旁路。
- **案件视图含合同审查**（用户拍板）：旧 `/cases` 覆盖的「协同/合同」两类在案件视图内延续。
- **零侵入**：仅新增前端页面与组件，未改动消息中心既有组件行为（IconRail 仅追加一项）。

**验证**：后端 `tests/test_memory_api.py` 假 store 同步 `starred` 签名，新增
`test_starred_create_filter_and_toggle`（创建置星标 / 默认非星标 / `starred=true` 过滤置顶 /
PATCH 切换）；全量后端 **347 passed**（346 + 1，无回归）。前端无 node 环境，仅做人工类型/路由核对。

**遗留**：旧文件 `app/cases/page.tsx` 现已被 `/cases → /memory?view=cases` 重定向取代，
其物理删除与其余旧路由（/chat→/messages、/knowledge→/search、/court→/messages）统一留待 T4.1。

### 3.20 T3.1 交付记录 ✅ —— `/api/search/unified` 统一案情搜索（四路并行）

对齐 [collab-ui-refactor_plan.md](collab-ui-refactor_plan.md) §4.4/§5.5：一个搜索框、后端并行多路召回、
前端按 Tab（`全部/法规/类案/我的记忆/会话记录`）过滤。

**范围（用户拍板）**：本卡**只做后端搜索 API**，把「转发到…」「引用并新建协同群」的接口留到 T3.2；
「类案」走**四级 RAG `domain=judge`**（与法规源一致，共享 HyDE 链路）；「会话记录」**纳入**第四路。

**实现**（`backend/app/routers/search.py`，新；`EnvelopeRouter` prefix `/api/search`）：
- `POST /api/search/unified`，请求体 `UnifiedSearchRequest`：`query`（必填，1–500）、
  `top_k`（默认 5，1–20）、`message_limit`（默认 10，1–50）、`use_hyde`（默认 true）、
  `case_id`（记忆按案件过滤，可选）、`sources`（可选子集，用于前端单 Tab 过滤）。
- `SearchBackend` 四路实现（`asyncio.gather` 并行，测试可 override `get_search_backend` 注入 fake）：
  - `law` / `judge` → 复用 `services/legal/rag_retriever.retrieve_legal_knowledge`
    （`domain=law` / `domain=judge`，flash 模型做 HyDE）；结果归一化为 `{type,content,source,score,domain,doc_type}`。
  - `memory` → 先 `is_memory_enabled(user_id)`（关闭则不读，与 T2.3 一致）→ `embed_text(query)` →
    `MemoryStore.similar(user_id, …)` → PG 逐条补水并过滤 `status=active`，复用 T2.3 召回范式。
  - `messages` → `select(Message, Conversation.title).join(Conversation)` 且
    `Conversation.user_id == 登录用户` + `content ILIKE`（`%`/`_`/`\` 已转义），按用户严格隔离。
- **失败隔离（fail-open）**：每路协程独立 `asyncio.wait_for`（预算 20s），任一路异常只置空该路 +
  写入 `errors{source:msg}` + 记日志，**其余三路不受影响，绝不 500**。
- 响应 `success({query, results{law,judge,memory,messages}, counts{…,total}, errors, took_ms})`：
  `results` 四键恒在（未检索的路为空列表），前端「全部」Tab 即四路拼接。

**验证**：新增 `backend/tests/test_search_api.py`（内存 `FakeBackend`，不依赖 PG/Qdrant/LLM）
5 例：四类结果各归其位 + counts、`sources` 子集过滤（未选路不触发）、非法 source → 40001、
空白/空串 query → 40001、单路失败隔离（judge 抛错时其余三路仍返回 + errors 记录）。
全量后端 **352 passed**（347 + 5，无回归）。

**遗留**：`/search/unified` 的转发/引用建群接口与前端搜索页（`app/search/*`、
`components/search/*`）、旧 `/knowledge` 收编 → T3.2（**已交付，见 §3.21**）。

### 3.21 T3.2 交付记录 ✅ —— 前端搜索页 + 转发/引用建群 + /knowledge 收编

对齐 [collab-ui-refactor_plan.md](collab-ui-refactor_plan.md) §4.4/§4.5/§5.5：统一搜索框 + Tab
（`全部/法规/类案/我的记忆/会话记录`），每条结果可「转发到…」「引用并新建协同群」，旧 `/knowledge` 收编为次级入口。

**范围（用户拍板）**：全量交付（页面 + Tab + 转发/引用建群，含新后端端点）；「转发到…」按
**仅作上下文卡片、不触发轮次** 语义实现。

**后端**（`backend/app/routers/conversations.py`）：新增 `POST /api/conversations/{id}/forward`
（`ForwardMessageRequest{card_type, citations[], content}`）：校验属主 → `store.insert_message`
（`msg_type=card`、`round=0`、`metadata={forwarded,card_type,citations,forward_source:"search"}`）
→ `push_recent_message` 进热缓存 + `_emit_message` SSE 广播；**不创建轮次**（返回 `turn_id=None`）。
空内容 → 40001。

**前端**：
- `app/lib/search.ts`：`/api/search/unified` 类型与请求、`forwardToConversation`，以及
  结果→引用卡/落库正文归一（`resultTitle/resultBody/resultToCitation/resultToForwardText/resultCardType`）。
- `store/useSearchStore.ts`：输入 / Tab / 四路结果 / 加载错误态；**始终四路全查**，Tab 仅前端过滤（切 Tab 不重复请求）。
- `components/search/*`：`SearchBar`（回车/热门词）、`SearchResults`（5 Tab + 计数 + 单路失败隔离提示 +
  每条「转发到…/引用并新建协同群」，会话记录另有「打开会话」）、`ForwardDialog`（选已有会话 → forward，不触发轮次）、
  `NewGroupFromQuoteDialog`（选案情模板 → 建群 → 引用内容作为首条发言起首轮协同）、`KnowledgeBrowsePanel`
  （法条/类案/策略分类树 + 单域语义检索，次级入口）。
- `app/search/page.tsx`：`IconRail` ｜ 主区（搜索模式 ↔ 知识库浏览模式）。
- `IconRail` 新增「案情搜索」入口；`AuthGuard` 将 `/knowledge` 重定向至 `/search`。
- `MessageBubble` 卡片标题映射扩展 `memory_citation→记忆引用`、`message_citation→会话引用`。

**验收对齐**：转发卡片以 `msg_type=card` 落入会话历史（`content` 为 `【标题】正文`），
进入后续轮次共享上下文窗，Agent 可引用；转发本身不消耗轮次。

**验证**：`backend/tests/test_conversations_api.py` 新增 3 例：转发落库 + SSE 且 `turn_id=None`、
空内容 → 40001、越权 → 40301；全量后端 **355 passed**（352 + 3，无回归）。
前端本机无 Node（WSL），仅人工核对类型 / 路由。

**遗留**：`app/knowledge/page.tsx` 物理删除与 `/search` 真机联调 → T4.1；T3.3 sse/http 韧性、T3.4 可观测。

### 3.22 T3.3 交付记录 ✅ —— SSE 自动重连收口 + 统一「重试」按钮（http 429 退避已有）

对齐验收 **O4「断网 30s 无重无丢」**。

**现状核查（关键发现）**：`http.ts` 的 429/502/503/504 指数退避（遵守 `Retry-After`、仅幂等 / 带 Idempotency-Key）
与 `sse.ts` 的自实现重连（重换票 + `last_id` 回放去重）在 T0.12/T1.8 **已具备**，本卡真正缺口有二：
1. 断线重连预算不足：原 `MAX_RETRIES=5`（延迟 0.5/1/2/4/8s，累计 ≈15.5s）撑不过 30s 断网 → 不满足 O4。
2. 「错误重试」按钮**误接**：`ConversationView` 的「重试」一律调 `retryLast()`（重发上一条文本），
   流断开时点它会误重发消息而非重连。

**改动**：
- `app/lib/sse.ts`：`MAX_RETRIES` 5→**12**、退避延迟封顶 **8s**（累计 ≈71s，覆盖 30s 断网）；
  句柄新增 `reconnect()`（重置退避计数并立即重建连接；用户已 `close()` 则无效）。
- `store/useCollabStreamStore.ts`：新增 `errorSource: 'stream'|'history'|'send'|'turn'|null`，在各错误落点标注来源；
  保存 `activeReconnect`；新增统一 `retry()`：`stream`→`reconnect()`、`history`→`open(conversationId)` 重载、
  `send|turn`→`retryLast()`（重发）。
- `ConversationView.tsx`：「重试」按钮改调 `retry()`（按来源分派），不再误重发。

**验收对齐**：断网 ≤30s 内自动重连 + `last_id` 回放 → 不丢不重（`id` 单调去重）；超预算或人为失败时
「重试」按钮可一键重连。

**验证**：前端本机无 Node（WSL），人工核对类型 / 调用链（`sse.ts` 句柄、store 各 error 落点、按钮分派）；
无后端改动（后端全量 355 passed 维持）。

**遗留**：O4 真机断网演练（切网 30s 观察无重无丢）建议与 T4.1 联调一并进行。

### 3.23 T3.4 交付记录 ✅ —— Prometheus+Grafana 可观测 + doc-tasks 异步 OCR 链路

对齐验收 **O7**。

**可观测**：新增 `deploy/observability/{prometheus.yml, grafana-provisioning/{datasources, dashboards}}`；
根 compose 加 `observability` profile 的 `prometheus`(:9090)/`grafana`(:3001)（默认不启，
`docker compose --profile observability up -d` 启用）；预置看板 `legalmind-overview` 覆盖
QPS/P95/5xx/重试/熔断/Kafka lag/worker 心跳（仅用既有指标名，标签低基数）。

**文档异步链路**：
- 新消费者 `worker/consumers/doc.py`：消费 `doc-tasks`，驱动 `ocr_service.ocr_file` 异步链路；
  逐条毒消息隔离，重试 `DOC_MAX_ATTEMPTS` 耗尽后发 `doc-tasks-dlq` 并把任务置 `failed` 再 ack；
  broker 不可达退化为仅心跳。
- `worker/main.py`：`doc` 角色由空转 `consume_standby` 改接 `consume_doc_tasks`（`consume_standby` 随之删除）。
- 入队点 `gateway.analyze_document`：Kafka 开启优先 publish `doc-tasks`（成功仅登记任务台账
  `create_task_record`，供前端 `/api/tasks/{id}` 轮询），关闭/降级回退旧 `enqueue_task`（行为兼容）；
  响应结构不变，前端无需改动。
- `redis_client.py`：抽 `_write_task_record`，新增 `create_task_record`（仅登记状态行、不投旧队列）。
- compose：`fastapi` 与 `worker-doc` 共享 `uploads_data:/app/uploads`（OCR 需读上传原件）；
  `worker-doc` 注入 `OCR_API_TOKEN`。

**验证**：`tests/test_doc_worker.py`（8 例：成功/skipped/DLQ/空文本/路径无法解析/消费派发+隔离/降级）
+ `test_redis_client.py` 补 2 例（仅登记不投队列/幂等）；全量后端 **365 passed**（355 + 10，无回归）。
前端本机无 Node，本卡不动前端；compose/observability YAML 与看板 JSON 已静态校验通过。

**遗留**：O7 真机端到端（`ENABLE_KAFKA=true` + `--profile observability` 起、上传文档→analyze→
轮询 completed、Grafana 看板）建议与 T4.1 联调一并进行。

### 3.24 T4.1 交付记录 ✅ —— 旧路由重定向（旧书签可达）

- `next.config.js` 新增服务端 `redirects()`：`/chat→/messages`、`/court→/messages?template=court`、
  `/knowledge→/search`、`/cases→/memory?view=cases`（`permanent:false`，过渡期跳转）。
- `components/AuthGuard.tsx` 将原先分散的旧路由分支收敛为单张 `LEGACY_ROUTE_MAP`
  （另含 `/dashboard→/messages`），作为客户端导航兜底；`/court` 目标补上 `template=court`。
- 物理删除旧页面文件 `app/{chat,court,knowledge,cases}/page.tsx`（合计约 2165 行）；
  这些历史 URL 现由服务端 `redirects()` 权威接管。

**验证**：本机无 Node（WSL），未跑构建；已静态核对——被删页无任何残留 import/引用、
四目录已空、`next.config.js` 与 `AuthGuard` 映射逐条对齐。

**遗留**：`/messages?template=court` 的 `template` 参数当前未被 `app/messages/page.tsx` 消费
（仅满足「旧书签可达」）；如需直达即预选「模拟法庭」模板，可在后续卡让 messages 读取该参数并预置建群向导。

### 3.25 T4.2 交付记录 ✅ —— 旧本地会话一次性迁移（direct 历史）

- 后端新增 `POST /api/conversations/import`（`routers/conversations.py`）：把旧 localStorage 会话
  导入为**服务端 direct 历史**。与 `send_message` 的关键差异——**不起新轮次**，沿用 `/{id}/forward`
  的落库范式：逐条 `insert_message` → `push_recent_message` → `_emit_message`（SSE 广播），
  `round=0`、`msg_type=text`、`metadata.imported=true`；使旧会话在新界面可见、可继续续聊。
- `insert_message` 增加可选 `created_at`（Protocol + `PgConversationStore`）：迁移时**忠实保留**
  旧消息原始时间戳；缺省仍走 `server_default=now()`，不影响既有调用方。
- 校验（越界统一 `40001`）：`messages` 非空且 ≤200 条、单条 `content` 非空且 ≤4000 字、
  `role ∈ {user, assistant}`、目标 Agent 须存在且启用（缺省 `general_assistant`）。
  发送者映射：`user→sender_type=user/sender_id=uid`；`assistant→sender_type=agent/sender_id=目标 Agent`。
- 前端 `app/lib/collab.ts` 新增 `importConversation(body)`；新组件
  `components/collab/LegacyMigrationBanner.tsx`：读 `legalmind_sessions:{username}`（与旧
  `useChatStore` 同键），非空且未设 `legalmind_migrated:{username}` 时，在 `app/messages/page.tsx`
  顶部显示引导条（含会话/消息计数）+「导入」/「稍后」；导入逐会话（≤20 会话、≤200 消息）调用
  `importConversation`，完成后置标志并 `fetchConversations()` 刷新列表。零侵入：失败仅提示、不阻塞。

**验证**：新增 5 个用例（建 direct + 发送者映射 + 原始时间戳保留 + 每条形 SSE 广播 + 不起轮次；
空/超量/非法角色/空内容/未知 Agent → 40001）；后端全量 **370 passed** 无回归。
前端本机无 Node（WSL），未跑构建；已静态核对类型与路由。

**遗留**：迁移目标固定为 `general_assistant` 单聊（旧会话未记录目标 Agent）；如需保留旧 `agent`
归属映射，可在后续卡扩展 `target_agent_id` 的按会话推断。

### 3.26 T4.3 交付记录 ✅ —— 旧端点标 deprecated + 删 LEGACY_RESPONSE 开关

- **删除临时开关 LEGACY_RESPONSE**（`core/config.py` 字段与注释、`core/response.py` 的 import 与
  `or settings.LEGACY_RESPONSE` 条件、`backend/.env.example`、`tests/test_envelope_legacy.py` 对应用例、
  `frontend/app/lib/http.ts` 注释）。信封中间件现恒按「新路由走 `EnvelopeRouter`、旧路由经
  `LegacyEnvelopeMiddleware` 统一穿信封」执行，不再有全局关信封的旁路。
- **旧端点标 `deprecated=True`（保留一个版本周期，代码不删）**：[gateway.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/gateway.py)
  的 `/chat`、`/chat/stream`、`/agents/run`、`/agents/stream`、`/debate/run`、`/debate/stream`、`/debate/kfe`
  共 7 个旧链路端点，各加中文 deprecation docstring 指向新 collab 链路。
- **旧 workflow 标 deprecated**：[legal_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/legal_workflow.py)
  的 `build_legal_workflow`、[debate_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py)
  的 `build_debate_workflow` docstring 各加 `.. deprecated:: T4.3`。
- **范围（用户拍板）**：仅标**已无前端引用**的旧链路；仍在使用的端点（`/api/knowledge/search`、
  `/api/knowledge/list`、`/api/dashboard/*`、`/api/contract/*` 等）**不动**。

**验证**：删除 `test_legacy_response_flag_disables_envelope` 1 个用例后，后端全量 **369 passed** 无回归。

### 3.27 T4.4 交付记录 ✅ —— 文档对齐当前代码事实

- [docs/architecture.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/architecture.md)（原为空文件）：
  系统总览/分层启动链/协同编排/记忆/搜索/四库四 Collection/Redis 键域/横切/14 条硬约束/技术栈。
- [docs/api-reference.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/api-reference.md)（原为空文件）：
  覆盖 **62 个端点**（新协同栈 28 + 旧 gateway 29 + 健康运维 5），逐一标注 7 个 T4.3 废弃端点，
  并单列「是否触发轮次」对照表（含 `/import` 否、`/forward` 否、`send_message` 是）。
- [docs/deployment.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/deployment.md)（原为空文件）：
  服务清单/端口/镜像 tag/四库初始化顺序/环境变量分组/Kafka KRaft/observability profile/裸机本地开发/
  微调模型/探针语义与降级矩阵/故障排查。
- [CODE_WIKI.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/CODE_WIKI.md)：879 → 1141 行，逐节更新至当前
  事实（TOC 与 `$1`–`$11` 章节一致），并把 §11「docs 文档」由 🔶 待补更新为 ✅ 已补齐。

**一致性抽查（trust-but-verify）**：核对端点计数（62）、镜像 tag、端口、容器名、SQL init 文件清单、
prometheus job 与 `deploy/observability` 目录结构均与仓库一致；修正 architecture.md 两处失真——
§9.8 旧前端重定向目标（补正 `/knowledge→/search`、`/cases→/memory?view=cases`、`/court→?template=court`，
并澄清旧**前端**页面文件已物理删除）与 §11 前端组件实际位置（在 `frontend/components/` 而非 `app/components/`）。

**如实标注的配置不一致**：根 `docker-compose.yml` 的 `fastapi` 段仍以
`DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}` 透传进 API 容器，与「LLM 密钥绝不进后端 API 容器」的硬约束
存在冲突；已在 deployment.md §5.5 按配置事实标注，**留待后续卡决定是否移除该透传**。

**验证**：文档为纯 Markdown 事实描述，无代码变更；抽查命令（`wc -l`、route decorator 枚举、
`ls backend/sql/init`、`find deploy/observability`、镜像/端口 grep）均已逐项比对通过。

### P2 — 长期记忆（Codex 式）

| ID | 任务 | 主要文件 | 验收 |
|---|---|---|---|
| T2.1 ✅ | Qdrant `user_memories`（1024/Cosine）；memories CRUD API（type/case/q 过滤、开关）（**已交付，见 §3.14**） | `core/qdrant_client.py`、`routers/memory.py`（新）、`services/memory/store.py`（新） | 增删改查+按 user 隔离 |
| T2.2 ✅ | memory-worker：turn 结束消费 memory-events → flash 抽取结构化记忆 → ≥0.90 合并/0.75-0.90 提示/<0.75 新增 → 重嵌入库；DLQ（**已交付，见 §3.15**） | `worker/consumers/memory.py`、`services/memory/{extractor,pipeline}.py`（新）、`services/collab/runner.py` | 两轮后自动出现记忆 |
| T2.3 ✅ | 对话链路 prepare 节点召回 top5 注入（独立 system 块）+ memory_recall 工具事件；用户关闭即不读不写（**已交付，见 §3.18**） | 接入 T1.3 prepare | 删除后不再召回 |
| T2.4 ✅ | 前端记忆页（分类 Tab/星标/来源跳转/编辑/删除/手动新增/总开关）+ 案件视图（替代旧 /cases）（**已交付，见 §3.19**） | `app/memory/*`、`components/memory/*`（新） | 手测通过 |

### P3 — 搜索 + 前端韧性 + 可观测收尾

| ID | 任务 | 主要文件 | 验收 |
|---|---|---|---|
| T3.1 ✅ | `/search/unified` 并行四路（四级 RAG law/judge + user_memories + messages ILIKE）；转发到会话/引用建群（留 T3.2）（**已交付，见 §3.20**） | `routers/search.py`（新） | 四类结果 Tab 正确 |
| T3.2 ✅ | 前端搜索页（`app/search/*`），转发/引用建群（`/conversations/{id}/forward` 上下文卡片，不触发轮次），旧 /knowledge 收编（**已交付，见 §3.21**） | `app/search/*`、`components/search/*`、`routers/conversations.py` | 转发卡片入群可被 Agent 引用 |
| T3.3 ✅ | sse.ts：Last-Event-ID 自动重连（预算扩至 ≈71s 覆盖 30s 断网）+ 统一「重试」按钮（按 errorSource 分派：重连/重载/重发）；http.ts 429 退避（已有）（**已交付，见 §3.22**） | `lib/sse.ts`、`lib/http.ts`、`store/useCollabStreamStore.ts` | O4 断网 30s 无重无丢 |
| T3.4 ✅ | Prometheus+Grafana（observability profile：prometheus/grafana  provisioning + 预置看板：QPS/P95/错误/重试/熔断/lag/心跳）；doc-tasks 走 OCR 异步链路（doc-worker 消费，旧 enqueue 兼容）（**已交付，见 §3.23**） | `deploy/observability/*`（新）、`worker/consumers/doc.py`、改文档分析入队点 | O7；OCR 异步任务端到端 |

### P4 — 收编、迁移、文档

| ID | 任务 | 验收 |
|---|---|---|
| T4.1 ✅ | 旧路由重定向：/chat→/messages、/knowledge→/search、/cases→/memory?view=cases、/court→/messages?template=court（**已交付，见 §3.24**） | 旧书签可达 |
| T4.2 ✅ | localStorage→服务端一次性迁移（登录后引导，导为 direct 历史）（**已交付，见 §3.25**） | 本地旧会话可见于新界面 |
| T4.3 ✅ | 旧端点/旧 workflow 标 deprecated（保留一个版本周期）；删 LEGACY_RESPONSE 临时开关（**已交付，见 §3.26**） | – |
| T4.4 ✅ | 更新 CODE_WIKI.md；补齐 docs/architecture.md、api-reference.md、deployment.md（当前为空文件）（**已交付，见 §3.27**） | 文档与实现一致 |

---

## 4. 文件全量清单

### 4.1 新增（后端）
```
backend/sql/init/04-app-schema.sql
backend/sql/init/05-seed-agents-templates.sql
backend/app/core/{response,errors,resilience,logging,tracing,events,checkpoint,metrics}.py
backend/app/routers/{conversations,collab,agents,memory,search}.py
backend/app/services/collab/{state,graph,host_skill,scheduler_skill,prompts,registry,runner,minutes,
                            agent_nodes,tool_nodes,production}.py
backend/app/services/collab/templates/{court,generic}.py
backend/app/services/memory/{extractor,store}.py
backend/app/worker/__init__.py  backend/app/worker/main.py
backend/app/worker/consumers/{collab,memory,doc}.py
backend/tests/test_{resilience,collab_graph,collab_guardrails,memory_service,
                    conversations_api,checkpoint_resume,events}.py
```
### 4.2 修改（后端，合同审查业务文件不动逻辑）
`Dockerfile`、`requirements.txt`、`.env.example`、`app/main.py`、`core/config.py`、`core/pg_client.py`、`core/llm_client.py`、`core/redis_client.py`、`core/qdrant_client.py`、`services/ocr_service.py`、`routers/gateway.py`（信封/错误/SSE error/文档入队）、`services/agents/judge_skill.py`（仅加 collab_mode 分支）、`sql/init/00-create-dbs.sql`、根 `docker-compose.yml`
### 4.3 新增（前端）
```
frontend/app/messages/[conversationId]/page.tsx, app/agents/, app/search/, app/memory/
frontend/components/collab/*（ConversationList/ConversationView/GroupOnboarding/
  AgentBubble/AgentStatusBar/ToolCard/MinutesCard/GroupInfoPanel/InteractionCard/
  RoundTimeline …）, components/memory/*, components/search/*
frontend/store/{useSessionStore,useCollabStreamStore,useMemoryStore,useUIStore}.ts
frontend/app/lib/{http,sse}.ts
```
### 4.4 修改（前端）
`components/Sidebar.tsx`、`app/layout.tsx`、旧 `app/lib/api.ts`（调用点切 http.ts）、旧页面重定向；**`app/documents/page.tsx` 与 `components/DocumentUpload.tsx` 仅做调用层适配，UI/业务不改**
### 4.5 基础设施新增
compose：`kafka`、`worker-collab/memory/doc`、`jaeger`；profile `observability`：`prometheus`、`grafana`；`deploy/observability/{prometheus.yml,grafana-provisioning/…}`；卷 `kafka_data`
### 4.6 明确不动
`services/workflows/{debate_workflow,contract_review_workflow,legal_workflow}.py` 的业务逻辑、`services/legal/*` 检索算法（convergence 词面算法仅旧庭审沿用）、9 个 Skill 中除 judge_skill 增分支外的其余文件、三知识库库 schema、三套 Qdrant 知识库 Collection、合同审查前端 UI

---

## 5. 依赖关系与开工顺序

```
T0.1 版本 ── T0.2 新库 ── T0.3 四引擎 ── T0.9 Checkpointer ─┐
T0.4 信封 ── T0.5 resilience ── T0.6 日志 ── T0.7 OTel      ├─ T0.12 旧端点切换(可并行收口)
T0.8 Kafka ── T0.10 worker 骨架 ── T0.11 探针/指标 ─────────┘
                                                              ↓ P0 闸门（回归通过）
T1.1 会话API/锁/SSE ── T1.2 注册表(+T1.1 补丁:字段/刷新恢复) ── T1.3 星型图 ── T1.4 HostSkill+SchedulerSkill
                                              ├── T1.5 Agent节点 ── T1.6 恢复引擎 ── T1.7 court
                                              └────────────────────────────  T1.8 前端（可与 T1.4-1.7 并行起步）
T1.* ── P2 记忆（prepare 已留 hook）── P3 搜索/看板 ── P4 收编迁移
```

- **当前进度（2026-10-17）**：P0 全部完成；**T1.1–T1.7 后端编排链路已全部交付**（T1.1 会话 API/锁/SSE、T1.2 注册表+补丁、T1.3 星型图、T1.4 HostSkill+SchedulerSkill、T1.5 Agent/Tool 节点、T1.6 恢复引擎 M1–M4、T1.7 court 模板配置化、T1.7⁺ 生产图全局接线，详见 §3.1–§3.8）。**前端 T1.8 消息中心：M1（三栏 IA 外壳）、M2（collab SSE 流式）、M3（建群向导）、M4（接管角标/交还、右栏群管理+Agent 时间线、纪要卡、checkpoints/fork「回到此轮」）已全部交付**（详见 §3.9）。**T1.8 全文完成；T1.9-M1（「结束会商」用户主权 / 注入 conclude，验收 F6）已交付**（详见 §3.10）。**T1.9 剩余 M2（会商纪要生成、`POST /{id}/minutes`）、M3（法规/类案引用卡）待续。**
- P1 交付节奏：一个模块一个模块交付，用 pytest fake LLM 验证；每张卡完成即勾掉并向您同步，P1 结束做一次演示验收。
- 派生项落位（三轮前端/架构澄清产生）：`my_role`（B3）与 `target_agent_id`（B1 数据层）随 **T1.2** 落地；前端刷新状态恢复（D16）归 **T1.1 补丁**；单聊只调目标 Agent（B1 执行层）归 **T1.5**；接管暂停/交还（B2）归 **T1.6**；**隐藏排序智能体（D14）归 T1.3/T1.4；辩论恢复特殊规则（D15）归 T1.6**。

---

## 6. 主要风险与对策（执行视角）

1. **旧端点信封切换回归面大** → T0.12 独立成卡 + `LEGACY_RESPONSE` 回滚开关 + 合同审查/庭审两条 SSE 流逐一手测；切换前后响应 JSON 快照对比。
2. **容器与本地 Python/依赖不一致** → T0.1 先解决（升 3.12、锁版本），CI/容器统一。
3. **主持人失控/死循环/偏心** → 三类护栏 + host_decisions 审计 + flash 出 directive 降本；max_rounds/预算硬顶。
4. **checkpoint 膨胀与并发写** → 30/90 天清理任务；thread 级 Redis 锁 + checkpoint 乐观并发。
5. **Kafka 增加开发负担** → ENABLE_KAFKA=false 全程可开发可测试；测试不依赖 Kafka（fake producer）。
6. **记忆幻觉** → 高阈值合并、可删可关、抽取 prompt 只允许明确陈述。
7. **Token 翻倍** → A4 策略（host flash、普通群 2 轮、预算 20 次/60k）。
8. **隐藏排序智能体（scheduler）决策不可见/失控** → 每次决策落 `host_decisions`（含 reason）供时间线审计；调用失败降级回退模板默认顺序；白名单/max_rounds 护栏照旧兜底；恢复时严格保序不跳人（D14/D15）。

---

## 7. P0 第一批具体提交（批准后我立刻动手的顺序）

1. `backend/Dockerfile`→3.12；`requirements.txt` 锁版本 + 新依赖，容器构建验证。
2. `sql/init/00-create-dbs.sql` 加 legalmind_app；新建 `04-app-schema.sql` + `05-seed-agents-templates.sql`。
3. `core/config.py` 配置项；`pg_client.py` 第四引擎与 ORM 模型。
4. `core/errors.py` + `core/response.py` + 全局处理器（先不切旧端点）。
5. `core/resilience.py` 并接入 llm_client（含单测）。
6. `core/logging.py` + request-id 中间件；`core/tracing.py` + compose jaeger。
7. compose kafka + `core/events.py`（带降级）。
8. `core/checkpoint.py`；worker 骨架与心跳；探针与指标。
9. T0.12 旧端点信封切换 + 前端 http.ts + 合同审查/庭审回归。
