# 多 Agent 调度澄清与群组协同细化规格（Spec）

> 日期：2026-10-15
> 关联文档：[collab-ui-refactor_plan.md](./collab-ui-refactor_plan.md)（上位计划，已批准方向；本文档细化"多 Agent 怎么调度、提示词怎么改"以及您锁定的 7 项决策）
> 状态：**待审批** —— 审批后作为后续实施（P0/P1）的直接依据

---

## 1. 先回答您的问题：现在的多 Agent 调度是法官做的吗？

**结论：不是。法官只是状态机里的一个"发言节点"，真正的调度器是 LangGraph 代码状态机；法官仅有一个"建议休庭补证"的软开关。**

代码位于 [debate_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py)，分三层：

### 1.1 谁决定"谁先谁后"——代码硬编码边（LLM 完全不参与）

[build_debate_workflow](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L616) 里 15 个节点的顺序由 `graph.add_edge` 焊死：

```
extract_kfe → check_evidence → retrieve_knowledge
→ judge_opening → plaintiff_opening → defendant_opening
→ court_investigation → plaintiff_rebuttal → defendant_rebuttal
→ judge_comment → convergence_check ─┬─(未收敛)→ plaintiff_rebuttal（循环）
                                     ├─(证据不足)→ END（等用户补证后重启）
                                     └─(收敛)→ judge_verdict → judgment_report
                                              → plain_language → finalize → END
```

**串行就是这样保证的**——每个节点内部 `await` 一个 Agent，完成才走下一条边，与提示词无关。

### 1.2 谁决定"走哪条分支"——4 个纯 Python 条件路由函数

| 路由函数 | 位置 | 判定依据 | 输出 |
|---|---|---|---|
| `route_after_evidence` | [L583](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L583) | `state.evidence_sufficient` | 继续检索 / END 补证 |
| `route_after_retrieve` | [L590](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L590) | `state.evidence_supplemented` | 正常开庭 / 补证后直入辩论 |
| `route_after_convergence` | [L598](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L598) | `evidence_needed` / `converged` | 再来一轮 / 裁决 / END |
| `route_after_verdict` | [L608](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L608) | `task_type` | 生成判决书 / 直接汇总 |

### 1.3 法官到底"管"什么——只有一个软开关

法官 4 次出场均在 [judge_skill.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/agents/judge_skill.py)：开庭（归纳焦点）、法庭调查（追问）、每轮点评、最终裁决。唯一能反向影响流程的是每轮点评方法 [evaluate_round](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/agents/judge_skill.py#L240) 输出的 JSON 里两个字段：

- `evidence_needed: true/false`
- `evidence_gap_description: "…"`

它们在 [judge_comment_node](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L328)（L346-L374）被解析写入 `state`，然后被 `route_after_convergence` 读取——**仅此而已**。法官不能指定下一个发言者、不能决定辩论收敛、不能叫停（叫停由代码算法决定，见下）。其 JSON 里的 `next_round_guidance` 只是当作 `last_judge_comment` 原文塞给律师"看一眼"，没有任何代码结构化消费它。

### 1.4 谁决定"停下来"——代码算法，不是法官

[convergence_check_node](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L378) 调用 [should_converge](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/convergence.py#L50)：最大 3 轮强制结束、词面 Jaccard×0.4 + 法律关键词重叠×0.6（注：目前是**词面**相似度，不是 embedding）、外加双方 KFE 一致性检查。

### 1.5 Agent 之间怎么"听见"彼此——State 字段人工传话

每个节点函数从 TypedDict 里取字段（`focus_points / plaintiff_args / defendant_args / judge_comments / legal_knowledge / kfe`），手工拼进下一个 Agent 的 HumanMessage（见 [plaintiff_rebuttal_node](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L234) 等）。没有共享黑板、没有自发对话、没有工具调用——全是节点间显式传递。

> **一句话模型：代码状态机 = 导演（定场次顺序+喊停）；法官 = 男主角兼场记（可以举牌"证据有问题"影响导演一次决策）；律师 = 按剧本轮流对词的演员。**

---

## 2. 群聊（拉群组）的调度该怎么做——把"法庭模式"泛化

### 2.1 设计原则：代码为骨架，主持人为软性信号

不把调度权交给 LLM（会不可控、不可重放、难测试），延续现有成熟分工：

1. **TurnOrchestrator（Python 代码）是唯一调度者**：决定轮次、顺序、终止、并发锁、事件推送，行为可单测。
2. **主持人 Agent 只产出结构化"主持建议"（HostDirective JSON）**：编排器解析后决定是否采纳；解析失败、越权、超时一律走代码默认值。这正是现有"法官 `evidence_needed` 软开关"的通用化，只是开关更多。
3. **成员 Agent 不感知调度**：各自只看到"群上下文块 + 自己的人设"，负责产出专业发言（详见 §3 提示词）。
4. **串行发言、一人一条独立消息（换行展示）**；检索类工具 Agent 在轮首并行预取，不占串行发言位。

### 2.2 模板与角色配置（表驱动，为后续加模板留口）

`case_roster_templates` 表字段（比上位计划细化）：

| 字段 | 说明 |
|---|---|
| `case_type` | 模板标识：contract / labor / marriage / tort / debt / realestate / court / custom |
| `name / icon / description` | 建群向导卡片展示 |
| `host_agent_id` | 主持人：court=judge；其余默认 mediator（婚姻/调解倾向）或 legal_analyst（可配） |
| `roster` | JSONB 数组，元素 `{agent_id, stage: opening\|debate, order}`，决定默认串行顺序 |
| `max_rounds` | 硬终止轮数：court=3（沿用现制），普通会商=2 |
| `minutes_enabled` | 收敛后是否自动出会商纪要 |
| `adapter` | `generic`（通用会商）/ `court`（模拟庭审，对接 debate_workflow） |
| `enabled` | 上下架开关；**后续新增模板 = 插一行数据 +（可选）写一个 adapter，编排器零改动** |

首批 8 个模板（host / roster 简表）：

| 模板 | 主持人 | 串行成员（顺序） | 轮次 |
|---|---|---|---|
| 合同纠纷 contract | 调解员 | 法务分析师→合同顾问→法规检索员→调解员 | 2 |
| 劳动争议 labor | 调解员 | 法务分析师→类案检索员→法规检索员→调解员 | 2 |
| 婚姻家事 marriage | 调解员 | 法务分析师→类案检索员→调解员 | 2 |
| 侵权纠纷 tort | 法务分析师 | 法务分析师→类案检索员→法规检索员 | 2 |
| 债权债务 debt | 法务分析师 | 法务分析师→法规检索员→合同顾问 | 2 |
| 房产纠纷 realestate | 法务分析师 | 法务分析师→类案检索员→法规检索员 | 2 |
| 模拟庭审 court | 法官 | 走 court adapter（原告→被告→法官点评 循环） | 3 |
| 自定义 custom | 法务分析师 | 用户勾选，默认 [法务分析师, 法规检索员] | 2 |

> 检索类 Agent（legal_researcher / case_searcher）`is_tool=true`：在轮首由编排器并行预取（发 `tool` 事件），结果入共享上下文；需要口头解释时再以一条独立气泡补充说明，不占用主串行序列。

### 2.3 一轮的调度时序（generic adapter）

```
用户消息（入库）
 │
 ├─ 含 @agent_id？──是──▶ 仅该 Agent 流式发言一条 ──▶ round_done（不调主持人、不推进轮次）
 │
 └─ 否（会商轮次）
     0. 获取分布式锁 lock:conv:{id}；round += 1
     1. 前置准备（全部发 SSE，对用户透明）：
        a. memory_recall  长期记忆召回（tool 事件）
        b. 首轮 retrieve：工具成员并行预取法规/类案（tool 事件）
     2. 首轮开场（仅 round=1 且模板 opening_enabled）：
        主持人一条"开场+争点归纳"气泡
     3. 串行发言：按 roster（非工具成员）逐个 await → typing → 流式 message
        每个 Agent 看到：人设 + 群上下文块（§3.2）+ 本轮此前所有发言
     4. 主持决策：调主持人 HostSkill.direct()，限 1 次调用、30s 超时、失败走默认
        解析 HostDirective（§2.4），编排器按 §2.5 规则裁决
     5. continue：进入下一轮（回到步骤 1b，轻量检索按需）
        conclude：书记员/主持人发纪要（可选）→ round_done → 触发 memory-events → 解锁
        need_user_input：发交互卡片（补证/补充信息/二选一）→ 挂起等用户下条消息 → 解锁
```

### 2.4 HostDirective 主持决策协议（新增 JSON Schema）

主持人每轮末尾输出"一段口语点评 + 一个 JSON 决策块"（思路沿用法官 [preside_opening](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/agents/judge_skill.py#L75) 双版本模式）：

```json
{
  "round_summary": "本轮各方共识与核心分歧（1-3句）",
  "directive": "continue | conclude | need_user_input",
  "next_speakers": ["legal_analyst", "mediator"],
  "need_search": { "query": "竞业限制经济补偿标准", "domains": ["law", "judge"] },
  "need_user_input": "需要用户补充的信息（directive=need_user_input 时填写）",
  "minutes": false
}
```

- `continue`：建议下一轮发言名单；`need_search` 非空时下一轮轮首补一次检索。
- `conclude`：分歧已充分或方案成型，编排器收尾（可由主持人发言给出结论建议）。
- `need_user_input`：信息/证据不足，需要用户补充（court 模板下即现有的"补证中断"）。
- 决策块以 ```json``` 包裹放在发言末尾，口语点评作为正常气泡展示；无 JSON 时按默认规则（未超轮次→continue 默认 roster；已达 max_rounds→conclude）。

### 2.5 编排器对 Directive 的"安全消费"规则（必须严格实现）

| 情况 | 编排器行为 |
|---|---|
| `@` 点名 | 最高优先级，只让被点成员发言，跳过主持人决策 |
| directive JSON 解析失败 | 默认：未达 max_rounds → continue + 模板默认 roster；否则 conclude |
| `next_speakers` 含非群成员/非法 ID | 过滤掉；全部非法则回退模板 roster |
| 主持人连续 2 轮给不出有效 directive | 代码强制 conclude，并发 `status` 小条说明 |
| 达 `max_rounds` 仍喊 continue | **代码否决，强制 conclude**（对应现有 max_rounds 硬终止） |
| 用户点「结束会商」按钮 | 立即 conclude（用户主权高于主持人） |
| 主持人调用超时/报错 | 跳过决策，默认 continue 一次；下一轮再失败则 conclude |
| 同群并发第二条消息 | Redis 锁拒绝并返回"会商进行中"，前端禁输入框 |

### 2.6 court adapter（模拟庭审模板，最大化复用）

不重写庭审：仍调用 [build_debate_workflow](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py#L616)，adapter 负责两件事：
1. **事件翻译**：把工作流节点（judge_opening/plaintiff_rebuttal/…）翻译成统一 SSE v2 事件，node→agent 映射沿用前端现有 `detectRole` 逻辑；`【speech:i】` 多气泡、`---NEXT---` 分段机制保留。
2. **调度对齐**：法官 `evaluate_round` 扩展字段（§3.3）兼容映射进 HostDirective（`evidence_needed → need_user_input`；收敛算法输出 → conclude）；补证中断变为群内「待补证卡片」，用户群内回消息即以 `evidence_supplemented=true` 重启（现有机制不动）。

这样"法官主持庭审"的体验不变，但群聊外壳、事件协议、记忆召回、持久化全部复用新架构。

---

## 3. 提示词改造规格

### 3.1 新增通用主持人提示词 `HOST_SYSTEM_PROMPT`（新文件 `services/collab/prompts.py`）

要点（供实施时展开为完整 prompt）：

- 角色定位：**你是本次法律会商的主持人，不是裁决者、不是检索工具**；职责是让讨论聚焦、有序、收敛。
- 你能看到：案情、群成员名单（含 agent_id 与专长）、完整 transcript、共享法规/类案材料。
- 每轮末尾必须输出：一段 100-200 字口语化主持点评（面向当事人，不要 JSON），随后附一个 HostDirective JSON 块（schema 见 §2.4）。
- 硬性约束：
  1. `next_speakers` 只能从**本群成员名单**中选，每轮 1-4 个，按发言顺序填写；
  2. 事实/法律检索自己不要做，需要时用 `need_search` 提出，由系统执行；
  3. 不重复成员观点，不复述案情；
  4. 同一分歧来回超过两轮或方案已成型 → `conclude`；关键信息缺失 → `need_user_input`；
  5. 不得输出任何调度指令文本给用户（JSON 块由系统解析，前端渲染为状态条/卡片）。
- 庭审模板不使用本 prompt，继续使用 `JUDGE_SYSTEM_PROMPT`（按 §3.3 增补）。

### 3.2 群上下文协议（统一拼接块，注入每个成员 Agent）

在不改动 9 个现有 Skill 人设 prompt 的前提下，由编排器在调用时统一拼接 HumanMessage 前缀：

```
【协同群】群名称：{title}　案情类型：{case_type_label}
【你的角色】{agent.role_label}——{agent.description}
【主持人本轮指引】{host.round_summary / next_round_guidance，首轮为争点归纳}
【已召回的用户背景记忆】{memories，top5；无则省略本块}
【共享资料】（系统检索，供引用，勿逐条罗列）
  ◇ 相关法规：{law_results}
  ◇ 类案参考：{case_results}
【本轮发言记录】（按时间顺序，最新在最后）
  法务分析师：……
  合同顾问：……
【输出要求】
  - 只输出你这一角色的专业意见，口语化、有条理，使用 Markdown 短段落
  - 不要重复上面别人已说过的内容；可引用《法律全称》第X条
  - 不要输出 JSON 或调度指令；长度建议 200-500 字
```

`@` 定向时追加：`【用户点名】用户 @你 提问："{原文}"，请仅回答该问题，不做全面分析。`

> 实施策略：**零侵入优先**——现有 Skill（PlaintiffSkill 等）的方法签名尽量不动，由 adapter 把统一上下文块映射为它们现有的入参（如 `case_facts / focus_points / legal_knowledge / debate_history`）。仅在确实无法承载主持逻辑时新增 HostSkill。

### 3.3 法官提示词增补（仅模拟庭审模板）

在 [JUDGE_SYSTEM_PROMPT](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/agents/judge_skill.py#L25) 末尾增加"协同群模式"小节（不启用群模式时不拼接，保证旧 `/debate/stream` 行为不变）：

- 告知"庭审在一个协同群中进行，群成员包括双方律师、书记员与当事人用户"；
- 将原"一、庭审流程控制：控制发言顺序"改写为：**通过每轮点评 JSON 中的 `next_speakers` 与 `directive` 字段向系统建议下一步**（可选项：plaintiff_lawyer / defense_lawyer / clerk；动作：continue / conclude / need_user_input），系统保有最终调度权；
- [evaluate_round](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/agents/judge_skill.py#L240) 的 JSON schema 增补两个**可选**字段 `directive`、`next_speakers`（旧字段全部保留，解析端双格式兼容）；
- 群模式下口语点评与 JSON 分两次产出（复用 `_split_speeches` 思路），避免当事人看到 JSON。

### 3.4 前端"换行"约定（对应您的 D3）

- 每个 Agent 每轮一条独立消息气泡，按 roster 顺序自上而下依次出现（typing 指示下一个是谁）；
- 同一 Agent 多段发言（如法官开庭 4 段）仍用现有 `speech:i` 机制拆成同一头像下的连续气泡；
- 轮次之间插入系统分隔条；**绝不把多个 Agent 的发言合并成一条消息**。

---

## 4. 您已锁定的 7 项决策（更新进总计划）

| # | 您的决定 | 落地口径 |
|---|---|---|
| D1 | 用**官方镜像** | 采用 Apache 官方 `apache/kafka:3.7.2`（内置 KRaft，无 Zookeeper），非 bitnami |
| D2 | 放**新库** | 新建 PG 库 `legalmind_app`（会话/群/成员/消息/Agent 注册表/模板/记忆），三知识库库不动 |
| D3 | Agent 发言默认**换行** | 串行调度，一人一条独立气泡；@ 可定向单人作答；主持人只建议顺序，代码保证串行 |
| D4 | `/court` **先收编**为模拟庭审模板 | court adapter 对接现有工作流；模板表驱动，后续按需继续加模板（加模板=插数据，不改编排器） |
| D5 | **旧接口也纳入 Harness** | 见 §5 全量改造与兼容策略（含合同审查） |
| D6 | 追踪系统**一直开启** | OTel SDK 默认启用、默认导出；Jaeger 进入 compose **默认服务**（不再放可选 profile），见 §6 |
| D7 | 接受双模式部署 | compose 全量（Kafka+3 worker+Jaeger）；`ENABLE_KAFKA=false` 支持轻量本地开发 |

---

## 5. D5 细化：旧接口全量纳入 Harness 的兼容策略

"全量"范围：现有 29 个端点（含 `/chat/*`、`/debate/*`、`/contract/*`、`/knowledge/*`、`/documents/*`、`/dashboard/*`、`/auth/*`）。分层处理，避免一次性炸雷：

1. **零感知层（直接全量加，前端无感）**：
   - `X-Request-ID` 中间件、structlog JSON 日志、Prometheus 指标补全；
   - 外部调用（llm_client / ocr_service / qdrant）统一走 resilience（重试/超时/熔断/降级）；
   - 全局异常替换为带错误码的信封；HTTP 状态码语义保持不变（401/403/404/429/502/503/504）。
2. **响应信封切换（前后端同一发布批次完成）**：
   - 成功：`{code:0,message:"ok",data:<原返回体>,request_id}`；原返回体整体下沉到 `data`；
   - 失败：`{code,message,detail,request_id}`，替换现有裸 `{detail}`；
   - 前端 `lib/http.ts` 统一解包，旧 `api.ts` 内所有调用点在同批次改掉；**合同审查页（DocumentUpload）与模拟法庭页逐条回归**。
3. **SSE 事件统一**：三类旧流式端点的 `error` 事件统一为 `{code,message,retryable,request_id}`；`message/metadata/done` 的**业务负载字段不变**，前端解析器仅加 envelope 兼容分支（新旧可识别一周）。
4. **数据库迁移与灰度**：信封改造无需迁移数据；后端加一个 `LEGACY_RESPONSE=true` 临时开关（默认 false），仅在回滚时使用，下阶段删除。
5. **验收红线**：合同审查三栏（条款树/原文/风险修订）、SSE 审查流、补证中断庭审流全部行为不变。

错误码总表（实施时落为 `core/errors.py` 枚举）：

| code | HTTP | 含义 | retryable |
|---|---|---|---|
| 0 | 200 | 成功 | – |
| 40101/40102 | 401 | 未登录 / token 过期 | false |
| 40301 | 403 | 无权限 | false |
| 40401 | 404 | 资源不存在 | false |
| 42201 | 422 | 参数校验失败（逐字段 detail） | false |
| 42901 | 429 | 限流 | true（Retry-After） |
| 50201 | 502 | LLM/外部服务调用失败（重试用尽） | true |
| 50301 | 503 | 熔断开启中 | true |
| 50310 | 503 | Kafka 不可用（已降级运行，提示性） | false |
| 50401 | 504 | 上游超时 | true |
| 50901 | 409 | 同群会商进行中（锁冲突） | false |

---

## 6. D6 细化：追踪常开

- 依赖：`opentelemetry-sdk`、`opentelemetry-instrumentation-fastapi`、`opentelemetry-instrumentation-httpx`、`opentelemetry-instrumentation-sqlalchemy`（可选 redis/asyncio）、`opentelemetry-exporter-otlp-proto-grpc`。
- 默认配置：`OTEL_ENABLED=true`（默认值即为开）、`OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`、service.name=`legalmind-api` / `legalmind-worker-collab` 等；trace 采样率默认 0.1（可配，排障临时调到 1.0）。
- compose 新增默认服务 `jaeger`（`jaegertracing/all-in-one:1.60`，内存存储，UI :16686），fastapi 与 3 个 worker `depends_on` 它；探针失败不阻塞启动（exporter 异步、带队列，Jaeger 挂了不影响业务）。
- 关键自定义 span 属性：`agent_id`、`turn_id`、`case_type`、`round`、`retry_count`、`model`；Kafka headers 透传 traceparent（W3C），worker 消费时续接同一 trace。
- 验收：Jaeger UI 能看到一条完整链路 `POST /collab/.../messages → kafka produce → worker consume → memory recall → RAG → 各 Agent LLM 调用`，SSE 订阅侧通过 request_id 可与该 trace 互查。

---

## 7. 需求清单与验收标准（Spec 验收口径）

### 7.1 功能性

| ID | 需求 | 验收标准 |
|---|---|---|
| F1 | 调度权在代码 | 单测：mock 主持人返回非法/越权 directive，编排器 100% 走默认规则；LLM 全程不决定边 |
| F2 | 串行换行 | 集成测试：3 成员群一轮产生严格按 roster 顺序的 3 条独立 message 事件，时间戳递增；前端 3 个独立气泡 |
| F3 | @ 定向 | 消息含 `@legal_researcher` 时仅其发言，不产生主持人决策事件，round 不递增 |
| F4 | 主持决策三态 | continue/conclude/need_user_input 各一个 mock 用例，事件与 DB 状态符合 §2.3 |
| F5 | 硬终止 | max_rounds=2 且主持人始终 continue 时，第 2 轮后强制 conclude |
| F6 | 用户主权 | 「结束会商」立即收尾；会商进行中再发消息返回 50901 |
| F7 | 庭审收编 | court 模板建群后事件序列与旧 `/debate/stream` 语义一致；补证卡片可在群内补证重启 |
| F8 | 加/移成员 | 群进行中加 Agent：下一轮起生效并出现在 next_speakers 白名单；移除后立即不可被点名 |
| F9 | 模板扩展 | 新增一个模板只需 INSERT 一行 + 不改 orchestrator 代码（用测试模板验证） |
| F10 | 降级运行 | ENABLE_KAFKA=false 时 F2-F6 在单进程内全部通过 |

### 7.2 Harness / 可观测性

| ID | 验收标准 |
|---|---|
| O1 | 所有日志 JSON 含 request_id；API→Kafka→worker 同一 request_id 可 grep 完整链路 |
| O2 | 模拟 5xx 上游：按 0.5/1/2s 退避重试最多 3 次，retry_total 指标 +3；熔断开启后返回 50301 |
| O3 | 全部 29 旧端点成功响应为信封 code=0，前端各页面回归通过（重点合同审查） |
| O4 | SSE 断网 10s 后用 Last-Event-ID 重连，缺口事件由 Redis Stream 补齐，不重复不丢失 |
| O5 | Jaeger 默认启动即可见 F1-F8 场景的完整 trace；关掉 jaeger 容器业务不受影响 |
| O6 | /healthz 不查依赖恒 200；/readyz 在 Redis 断开时 503 |
| O7 | worker 心跳 key TTL 30s，停 worker 后 Grafana 心跳面板告警；Kafka lag 面板有数 |

---

## 8. 任务分解（在上位计划 P0-P4 上的细化/修订）

**P0 工程地基（修订）**
- T0.1 `04-app-schema.sql`（含 §2.2 模板表完整字段 + 8 模板种子数据 + 10 Agent 注册表种子）
- T0.2 `core/errors.py` 错误码枚举 + `ApiResponse` 信封 + 业务异常；全局异常处理器切换
- T0.3 `core/resilience.py`（tenacity 重试/超时分层/熔断服务名隔离/降级包装）接入 llm_client、ocr_service
- T0.4 structlog + request_id contextvar 中间件
- T0.5 OTel 常开配置 + Jaeger compose 服务 + traceparent 透传约定
- T0.6 apache/kafka 3.7.2 KRaft 服务 + `core/events.py`（aiokafka，ENABLE_KAFKA 降级）
- T0.7 worker 骨架（心跳/8001 探针与指标/优雅停机）
- T0.8 旧端点信封全量切换 + 前端 http.ts 解包改造（同批次），合同审查/庭审回归

**P1 群组协同（修订）**
- T1.1 conversations/members/messages API + Redis 缓存 + 轮次锁（50901）
- T1.2 `services/collab/prompts.py`（HOST_SYSTEM_PROMPT + 群上下文块构造器）
- T1.3 HostSkill（direct：口语点评 + HostDirective 双输出、JSON 容错提取）
- T1.4 TurnOrchestrator（§2.3 时序 + §2.5 安全消费规则，含 @ 解析）
- T1.5 generic adapter + court adapter（节点事件翻译/补证卡片）
- T1.6 SSE v2：短票据、Stream 回放、Pub/Sub 桥接、typing/tool/message/round_done/done/error
- T1.7 collab-worker 消费（Kafka 模式 + 进程内降级双模式）
- T1.8 前端三栏 IA、消息列表、建群向导、群聊气泡/状态条/工具卡/纪要卡/@、右栏群管理
- T1.9 模板管理（成员加立即生效/移除白名单）

**P2 长期记忆**：同上位计划（召回事件接入编排器步骤 1a，结果进 §3.2 上下文块）
**P3 搜索 + 前端韧性 + 看板**：同上位计划
**P4 收编迁移**：court 收编提前到 P1（T1.5）；P4 仅余旧路由重定向、localStorage 迁移、CODE_WIKI/docs 更新

---

## 9. 两个需要您知晓的实现取舍

1. **现有"语义收敛"其实是词面算法**（Jaccard+关键词，见 [convergence.py L83](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/convergence.py#L83)）。新群聊 generic 模板不沿用它，改由"主持人 directive + max_rounds 双保险"；court adapter 保持现有算法不变（避免影响庭审）。是否升级为 embedding 相似度列为后续可选项，不在本期。
2. **9 个现有 Skill 文件尽量零改动**：群上下文通过 adapter 映射为现有方法入参；真正新增的提示词只有 `HOST_SYSTEM_PROMPT` 和法官的"群模式可选小节"。这样合同审查与旧庭审链路的回归面最小。

