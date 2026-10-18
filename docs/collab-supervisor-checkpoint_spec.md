# 修订规格：法官/主持人驱动的动态调度 + 中断恢复/异常回退机制

> 日期：2026-10-15
> 本文是对 [collab-scheduling_spec.md](./collab-scheduling_spec.md) 的**架构修订**：您提出"用 LangGraph 就要利用框架，不应代码写死策略"，故将"代码状态机决定顺序"改为"法官（主持人）通过 LangGraph `Command(goto=)` 决定下一回合"。
> 环境已核实：实际安装 **LangGraph 1.2.1 / langgraph-checkpoint 4.1.1 / langchain-core 1.4.0**（远新于 requirements 声明的 0.2），动态路由 `Command(goto=)`、函数式 `interrupt()` + `Command(resume=)`、`aget_state_history` 时间旅行均为稳定 API。

---

## 1. 架构修订总览

**职责重新划分：策略归 LLM，护栏归代码，状态归 Checkpointer。**

1. **调度策略（谁下一个发言、要不要补充提问、是否需要检索、何时收敛/裁决）全部由法官（普通群为主持人）在运行时决定**，通过 LangGraph 节点返回 `Command(goto=...)` 实现动态路由——图中**不存在任何指向业务节点的固定边**。
2. 代码只保留三类**工程护栏**（不构成业务策略）：① 跳转目标白名单；② max_rounds 轮次硬顶与预算；③ 主持人输出格式校验与一次自我修复。
3. 图状态全部交由 **LangGraph Checkpointer（Postgres 持久化）** 管理：业务中断用原生 `interrupt()/resume`，系统异常按 super-step 自动续跑，手动回退用 state history 时间旅行。
4. 旧 [debate_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py) 15 节点固定工作流**保留不动**（旧端点零回归）；新群聊（含"模拟庭审"群模板）使用本规格的新星型图。

---

## 2. 主持人驱动的星型图（Hub-and-Spoke）

### 2.1 图结构：一个主持人中心 + 若干发言/工具辐条

```
START → prepare ─→ host ─┬─(Command goto)─→ agent:plaintiff_lawyer ─┐
                         ├────────────────→ agent:defense_lawyer ──┤
                         ├────────────────→ agent:legal_analyst ───┤
                         ├────────────────→ agent:mediator …       │ 每个 spoke
                         ├────────────────→ tool:legal_search ─────┤ 完成后固定
                         ├────────────────→ tool:case_search ──────┤ 回到 host
                         ├────────────────→ ask_user (interrupt) ──┤
                         └────────────────→ conclude ─→ END        ┘
```

- **host 是唯一的路由决策点**：每个 Agent/工具节点结束后只有一条固定边回 host；
- Agent 节点由**节点工厂按注册表统一生成**（注册表 10 个 Agent → 10 个 `agent:{id}` 节点），模板 roster 与群成员变更只影响 host 的**白名单集合**，不增删图结构；新增 Agent 类型 = 注册表加一行 + 工厂自动出节点；
- 工具节点（法规/类案检索）与发言节点同级，主持人需要材料时 goto 工具，工具产出回 host 再决策。

代码骨架（实际实施文件 `services/collab/graph.py`）：

```python
graph = StateGraph(CollabState)
graph.add_node("prepare", prepare_node)     # 长期记忆召回 + 首轮共享材料预取
graph.add_node("host", host_node)           # 法官/主持人：LLM 决策 → Command(goto=)
graph.add_node("ask_user", ask_user_node)   # 内部调用 interrupt()，等待用户补证/补充
graph.add_node("conclude", conclude_node)   # 裁决书 / 会商纪要 → END

for agent in AGENT_REGISTRY:                # 节点工厂，业务顺序零硬编码
    graph.add_node(f"agent:{agent.id}", make_agent_node(agent))
for tool_id in ("legal_search", "case_search"):
    graph.add_node(f"tool:{tool_id}", make_tool_node(tool_id))

graph.add_edge(START, "prepare")
graph.add_edge("prepare", "host")
for spoke in [f"agent:{a.id}" for a in AGENT_REGISTRY] + ["tool:legal_search", "tool:case_search"]:
    graph.add_edge(spoke, "host")           # 所有发言/工具结束 → 回主持人
graph.add_edge("ask_user", "host")          # resume 后先回主持人重新决策
graph.add_edge("conclude", END)
# 注意：没有任何 add_edge("host", 某个固定业务节点)——host 的去向 100% 运行时决定
```

### 2.2 图状态 CollabState

```python
class CollabState(TypedDict):
    messages: Annotated[list, add_messages]  # 统一 transcript：user/host/agent/tool
    conversation_id: str                     # = checkpoint thread_id（跨轮次长期连续）
    turn_id: str                             # 本次用户发言触发的一轮会商
    case_type: str
    roster: list[str]                        # 当前群成员（加人/移除即时改变白名单）
    round: int                               # host 每完成一次决策 +1
    max_rounds: int                          # court=3，普通会商=2
    host_directive: dict                     # 最近一次主持决策（审计/恢复用）
    memories: list                           # prepare 召回的长期记忆
    retrieved: dict                          # 共享法规/类案材料
    pending_question: str | None             # ask_user 要用户补什么
```

一次用户发言 = 一次 `astream` 驱动：图在 `ask_user`（暂停）或 `conclude`（END）处结束本次执行，**checkpoint 保留全部状态**；用户下一条消息带着新输入从同一 thread 继续。

### 2.3 host 节点：法官如何"决定下一回合干什么"

host 节点先让主持人 LLM 产出两样东西（双输出，沿用法官 Skill 现有的 JSON+自然语言模式）：① 一条给当事人看的口语发言（写入 transcript，前端正常气泡）；② 一个 `HostDirective` 结构化指令：

```json
{
  "round_summary": "本环节各方观点与分歧（1-3句）",
  "directive": "continue | ask_user | verdict | conclude",
  "next": "agent:plaintiff_lawyer",
  "ask_user": "需要用户补充的具体信息/证据（directive=ask_user 时）",
  "search_request": { "query": "竞业限制经济补偿", "domains": ["law", "judge"] },
  "reason": "为什么安排这一步（写入 host_decisions，展示给用户审计）"
}
```

随后节点执行**护栏过滤**并返回 Command：

```python
async def host_node(state: CollabState) -> Command:
    decision = await host_skill.decide(state)          # LLM：发言 + directive
    await record_host_decision(decision)               # host_decisions 审计落库

    # —— 以下是工程护栏，不含任何业务顺序策略 ——
    if decision.directive == "ask_user":
        return Command(goto="ask_user",
                       update={"host_directive": decision.dict(),
                               "pending_question": decision.ask_user})
    if decision.directive in ("verdict", "conclude"):
        return Command(goto="conclude", update={"host_directive": decision.dict()})
    if state["round"] + 1 > state["max_rounds"]:       # 轮次硬顶：LLM 无法突破
        return Command(goto="conclude",
                       update={"force_stop_reason": "max_rounds"})

    allowed = set(state["roster"]) | {"tool:legal_search", "tool:case_search"}
    if decision.next in allowed:
        return Command(goto=decision.next,
                       update={"host_directive": decision.dict(),
                               "round": state["round"] + 1})
    # 非法目标 → 带反馈在本 super-step 内重新询问主持人（见 §2.4）
    repaired = await host_skill.repair(state, decision, invalid_target=decision.next)
    goto = repaired.next if repaired.next in allowed else "conclude"
    return Command(goto=goto, update={"host_directive": repaired.dict()})
```

庭审模板下 directive 取值 `continue/ask_user/verdict`（法官还可 `next=judge_investigation`，实现为 judge 自带的法庭调查子能力节点）；普通会商取 `continue/ask_user/conclude`。

### 2.4 代码护栏的完整清单（仅三类，且全部可观测）

1. **跳转白名单**：`next` 必须是当前 roster 成员或两个工具节点；群进行中加人——下一次 host 决策即生效；移除——立即不可被 goto；
2. **轮次与预算硬顶**：`max_rounds` 强制 conclude；另设单次 turn 的 LLM 调用总次数与 token 预算（默认 20 次 / 60k tokens），超限同样强制收尾，护栏触发原因写入 `host_decisions.rejection_reason`；
3. **输出格式校验 + 一次自我修复**：directive JSON 解析失败/枚举非法 → 不移动图位置，在同一 super-step 内带格式错误反馈再调一次 host（不跳新 Agent、不新增 round）；
4. 再次失败 → 代码兜底 `goto=conclude`，SSE 提示"主持决策异常，按已完成讨论出具阶段性意见"；
5. 节点内所有 LLM 调用经 resilience 层：**retry 3 次（0.5/1/2s 退避）→ 熔断检查 → 仍失败则抛异常使该 super-step 失败**（交给 §3 恢复），绝不在节点内吞掉错误输出半成品结论。

### 2.5 两种主持人的差异化（同协议、不同人设）

| | 模拟庭审 court | 普通会商（合同/劳动/婚姻…） |
|---|---|---|
| 主持人 | **法官 judge**（正式庭审权力：焦点归纳、追问、决定辩论轮次、裁决） | 调解员 mediator / 法务分析师 legal_analyst（按模板配置） |
| 终止输出 | `verdict` 裁决 + clerk 判决书节点（沿用 JudgeSkill/JudgmentReportSkill） | conclude 节点的《会商纪要》（clerk 或 host 兼） |
| 追问形式 | `ask_user` = 补证中断（对齐现有"证据不足→补证"业务） | `ask_user` = 补充事实/材料（语气为"麻烦您再提供…"） |
-|-|-|
| 循环动机 | 保证双方充分对抗、焦点收敛后裁决 | 快速形成可执行意见，默认 max_rounds=2，鼓励主持人尽早 conclude |
| 模板示例 | roster 固定为原告律师/被告律师/书记员，host=judge | roster 来自 case_roster_templates（§前序规格 §2.2 的 8 模板），host 按模板 |

> 即：**模板定义"初始 roster 与主持人是谁"，主持人定义"每一步怎么走"**。模板给的是开局阵容，不是剧本。庭审模板就是 host=judge 的一个配置项，不再需要独立的 15 节点工作流（旧 [debate_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py) 保留给旧端点不动，见 §5）。

### 2.6 与前序规格的差异对照

| 条目 | 前序规格（已作废/修订） | 本规格 |
|---|---|---|
| 发言顺序 | 代码按模板 roster 硬编码串行 | host LLM 用 `Command(goto=)` 动态决定，含跳过/加场/追问/终止 |
| 循环 | 固定"全员轮流→主持决策" | host 可在任意发言后接管（每个 spoke 都回 host） |
| 补证 | 卡片+手工重启标志位（沿用旧法） | 原生 `interrupt()` 暂停 + `Command(resume=)` 恢复，废弃手工重启 |
| 收敛 | 词面相似度算法 + 软开关 | 法官/主持人综合判断 conclude（附裁判规则/分歧对照），代码只保 max_rounds 硬顶 |
| F1 验收 | "LLM 全程不决定边" | 改为"LLM 决定业务走向，代码只强制白名单/轮次上限/格式校验三类护栏" |
| court adapter | 包装旧工作流做事件翻译 | court 直接是新星型图的一个配置；adapter 仅负责提示词与节点能力绑定 |

---

## 3. 中断恢复与异常"回到上一轮"（您问的核心）

依托 LangGraph Checkpointer，区分 **4 种情形**，前 3 种完全由框架机制承接：

### 3.1 情形 A：业务中断（补证/补充材料）—— `interrupt()` 精确暂停与恢复

```
host 判定 need_user_input
 → 图进入 ask_user 节点 → payload = interrupt({...}) 抛出 GraphInterrupt
 → 当轮 super-step 的状态（transcript/round/争点/各 Agent 已发言）原子写入 PG checkpoint
 → turns.status = interrupted；SSE 推 interaction_required 卡片（写明要补什么）
 → 图在物理上"挂起"，不占 worker

用户在群内回复（文字/附件）
 → worker 用同一 thread_id 调 graph.astream(Command(resume=用户补充内容), config)
 → 从 ask_user 之后精确继续：补充材料入 transcript → 回到 host → 法官决定下一步
```

要点：
- 恢复点是**节点级精确位置**，不是像现在 [gateway.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/gateway.py#L1112) 那样整个工作流重跑、再靠 `evidence_supplemented` 标志位跳过开庭——该 workaround 在新图中删除（旧端点保留旧逻辑）；
- 中断期间用户可以继续发普通消息：API 层把消息缓存入 `messages` 表，恢复时一并作为 resume 上下文；
- 中断没有超时压力：checkpoint 在 PG 里，三天后补证也能续。

### 3.2 情形 B：系统异常（LLM 超时/Worker 崩溃/重启）—— 从最近 checkpoint 自动续跑

LangGraph 在**每个 super-step（节点跳转）成功后原子提交 checkpoint**。恢复协议：

```
worker 消费 turn 消息（或重启后从 Kafka 重投拿到未 ack 的消息）
 → 查 turns.status：
     completed → 幂等 ack，直接跳过
     failed/interrupted/running(租约过期) → 续跑：
         graph.astream(None, config={thread_id, checkpoint_id=最近成功checkpoint})
 → 已完成的节点不会重跑；只有失败的那个 super-step（整个节点）重新执行
 → 成功后正常 ack Kafka；连续 N 次（默认 3）仍失败 → 进 DLQ + turns.status=failed
   SSE 推 error(retryable=true)，前端展示"从上一轮重试"按钮
```

工程细则：
1. **LLM 半截响应不保留**：节点失败 = 该 Agent 整条发言重新生成（不续写半截文本，避免语义错乱）。这是明确取舍，换取简单与正确；
2. **幂等键防重复落库/推送**：消息与 SSE 事件使用确定性 ID：
   - message id = `{turn_id}:r{round}:{agent_id}:{seq}`
   - PG `messages` 对该 id `INSERT ... ON CONFLICT DO NOTHING`；Redis Stream 的 XADD 由"先查库后发"保证不重，前端以 id 去重兜底；
3. **worker 租约**：`turns.worker_heartbeat` 每 10s 续租，90s 无心跳视为僵死，Kafka 分区再平衡或其他副本接管续跑（同一 turn 永远只有一个执行者，Redis 锁 + PG `running` 状态双重保险）；
4. **熔断开启时**：host/agent 节点根本不会发起 LLM 调用前先查熔断器，开路则节点快速失败 → 走同一条 checkpoint 恢复路径，熔断恢复后由用户点重试或 worker 定时扫描 failed turn 自动复活；
5. **SSE 断线 ≠ 图失败**：图在 worker 里独立运行，SSE 只是 Redis Stream 的投影；用户刷新/断网后 Last-Event-ID 回放，图进度不受任何影响。

### 3.3 情形 C：手动"回到上一轮"（时间旅行 / Time Travel）

用户（或管理员）对某轮结果不满意，要退回重审：

```
GET /conversations/{id}/turns/{turn_id}/checkpoints
 → graph.aget_state_history(config) 列出该 turn 的 checkpoint 链
 → 每个 host 决策点记录：轮次、法官指令(directive)、时间、关联消息
 → 前端展示为"回合时间线"（与 Agent 动态时间线共用 UI）

用户点"回到第 N 轮重新会商"
 → 以该 checkpoint_id 调 graph.astream(None / Command(update=修正), {checkpoint_id})
 → LangGraph 从该点 fork 出新分支（旧分支保留不丢）
 → 之后的消息标记 forked_from={turn_id, checkpoint_id}
```

- 回到上一轮时可附带 `aupdate_state` 修正事实（如用户发现自己案情描述错了）；
- 庭审模板下这就是"回到法庭调查阶段重新举证辩论"；
- 第一版只支持**整条 turn fork 重跑**，不做跨 turn 的任意节点穿越（避免状态依赖混乱，列为后续可选）。

### 3.4 情形 D：主持人决策非法/失控 —— 同 super-step 内自我修复（不回退）

见 §2.4：解析失败 → 带错误反馈再调一次 host（图仍在同一个 host super-step 内，不算回退、不产生重复发言）；二次失败 → 强制 conclude。法官想点不在群里的 Agent → 过滤并在反馈中告知"可用名单"。

### 3.5 恢复全景对照表

| 情形 | 触发 | 机制 | 恢复到哪 | 用户感知 |
|---|---|---|---|---|
| 补证/补充信息 | host 指令 ask_user | `interrupt()` + `Command(resume=)` | ask_user 之后精确位置 | 群内出现待办卡片，回复即继续 |
| LLM 调用失败 | 超时/5xx/断连 | resilience 重试→节点失败→checkpoint 重放 | 失败节点（整个 Agent 发言重来） | 状态条"重试中"；用尽后给重试按钮 |
| Worker 崩溃/发布重启 | 进程消失 | Kafka 重投 + 心跳租约 + checkpoint | 最后完成的 super-step 之后 | SSE 短暂缓冲后继续，不丢已完成发言 |
| 用户主动回退 | 点时间线 | state history + checkpoint_id fork | 指定轮次（旧分支保留） | 从该轮重新会商 |
| 主持决策格式错 | LLM 输出不合规 | 同节点反馈重调 1 次 | 不移动位置 | 无感（修复成功）/ 直接出纪要 |
| SSE 断线 | 网络问题 | Last-Event-ID + Redis Stream | 事件流位置 | 自动补齐，图不受影响 |

---

## 4. 配套数据模型与依赖增量

### 4.1 新增表（并入 `legalmind_app` 库，`04-app-schema.sql`）

```sql
-- LangGraph checkpoint（AsyncPostgresSaver.setup() 自动建表，不手写）：
-- checkpoints / checkpoint_writes / checkpoint_blobs，thread_id 存 conversation_id

-- 每轮触发的执行台账（恢复与幂等的权威依据）
collab_turns(
  turn_id UUID PK, conversation_id FK, user_id,
  trigger_message_id,
  status VARCHAR(running/interrupted/completed/failed),
  mode VARCHAR(kafka/inprocess),
  worker_id VARCHAR, worker_heartbeat TIMESTAMPTZ,
  attempts INT DEFAULT 0,
  last_checkpoint_id VARCHAR,        -- 最近成功 super-step
  error JSONB,                       -- 最后一次错误码/信息/request_id
  forked_from_turn_id UUID NULL,
  created_at, updated_at, completed_at
)

-- 主持人决策审计（可观测性：回答"法官为什么让他发言"）
host_decisions(
  id BIGSERIAL PK, turn_id, conversation_id, round INT,
  host_agent_id, raw_output TEXT, parsed_directive JSONB,
  accepted BOOL, rejection_reason VARCHAR,   -- 被白名单/轮次护栏否决时记录
  request_id VARCHAR, latency_ms INT, created_at
)
```

`messages` 增加 `event_key VARCHAR`（确定性幂等键，唯一索引）、`checkpoint_id VARCHAR NULL`、`fork_parent VARCHAR NULL`。

### 4.2 依赖

- `requirements.txt` 新增：`langgraph-checkpoint-postgres>=2.0`（提供 `AsyncPostgresSaver`，走 asyncpg，连接 `legalmind_app`）；
- 应用启动时 `await checkpointer.setup()` 幂等建 checkpoint 表；
- 图实例**不做全局单例**：图结构无状态可复用单例，checkpointer 单例；每次执行按 `config={thread_id}` 区分会话；
- Kafka headers 透传 `conversation_id/turn_id/request_id/traceparent`，worker 据此恢复同一上下文。

### 4.3 turns 状态机

```
running ──host ask_user──▶ interrupted ──resume──▶ running
running ──全部节点成功──▶ completed（终态，Kafka ack）
running ──attempts≥3──▶ failed（DLQ；可由用户/定时任务重试→running）
任意时刻 worker 心跳超时 → 被视为 running 孤儿 → 抢占续跑
```

---

## 5. 旧模拟法庭工作流的处置（不违反"旧接口零回归"）

- 旧 `/api/debate/stream`、`/debate/run`、[debate_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py) **代码与行为完全保留**，D5 只对其加 Harness 横切能力（信封/日志/重试/追踪）；
- 新"模拟庭审"群模板走新星型图（host=judge），旧页面 `/court` 在 P4 重定向到该群模板后，旧工作流进入只读维护（不删，保留一个版本周期）；
- JudgeSkill 的提示词增补在新链路生效；旧 workflow 仍调原提示词（通过参数 `collab_mode=False` 区分，默认 False）。

---

## 6. 法官/主持人提示词增补（调度权授予，替换前序规格 §3.1 的保守写法）

`JUDGE_SYSTEM_PROMPT` 增补章节（collab_mode=True 时拼接）核心条文：

```
## 庭审调度权（协同群模式）
你不仅主持庭审，还拥有下一步的调度权。每完成一个环节，你必须输出：
1）面向当事人的口语化主持发言（100-300字，不允许出现 JSON）；
2）紧随其后的一个调度指令 JSON：
{
  "round_summary": "本环节结论与分歧",
  "directive": "continue | ask_user | verdict",
  "next": "plaintiff_lawyer | defense_lawyer | judge_investigation | legal_search | clerk",
  "ask_user": "需补充/举证的具体内容（directive=ask_user 时）",
  "search_request": {"query": "...", "domains": ["law","judge"]},
  "reason": "你为什么选择这一步（内部审计用，会展示在时间线）"
}
调度规则：
- 双方未充分对抗前不得 verdict；事实不清优先 ask_user 或法庭调查；
- 同一焦点已辩论两轮无新观点 → verdict；next 只能选择群内存在的角色；
- 需要法规/类案时不要自己检索，发 legal_search，系统会把材料带回给你；
- 指令是给系统的，必须严格合法 JSON，放在 ```json 代码块中。
```

普通会商主持人用结构相同、措辞中立的 `HOST_SYSTEM_PROMPT`（directive 取值 continue/ask_user/conclude；next 从动态 roster 选择；强调"你是协调者不是裁判，促成可执行意见，避免无限讨论"）。

**主持人决策质量保障**：
- prompt 内置"决策树指引"（信息齐→先检索→逐角色发言→分歧归类→收敛/追问），但**不规定固定顺序**，由主持人根据案情裁量；
- `reason` 字段强制让法官说明调度理由，落 `host_decisions` 表，前端时间线与 Grafana 都能审计；
- 一期不做主持人决策的 LLM 评委；通过 max_rounds/白名单护栏兜底。

---

## 7. 修订后的验收标准（替换前序规格 §7.1 F1/F4/F5 等）

| ID | 验收标准 |
|---|---|
| F1（新） | 法官连续两轮输出 `next=plaintiff_lawyer`（在案情需要充分对抗时）图正确循环；输出 `next=legal_search` 时跳检索工具节点后回法官；**走向全部出自 LLM 指令，代码无业务顺序分支**（代码评审 + 日志证明） |
| F2 | 同前：每个被点到的 Agent 产出独立气泡，严格换行 |
| F3 | @ 点名走用户消息直达 agent 节点（host 事后接管评议），不触发 ask_user |
| F4（新） | 补证中断：checkpoint 落库、turns=interrupted；resume 后从 ask_user 之后继续，**此前各 Agent 发言不重新生成**（用 event_key 计数证明） |
| F5（新） | max_rounds=2 且法官持续 continue：第 3 次进入 host 被代码强制 goto conclude，host_decisions 记录 rejection_reason=max_rounds |
| F6 | 「结束会商」用户按钮直接向图注入 goto=conclude（用户主权通过 Command(update/goto) 实现） |
| F7（新） | 庭审模板在新星型图完成开庭→对抗→补证→恢复→裁决全流程；旧 /debate/stream 回归不变 |
| F11 | **故障演练**：①Agent 发言中 kill worker → 重启后从最后 super-step 续跑，已完成发言不重复；②LLM 端点返回 500 三次 → turns=failed/DLQ，点重试成功；③断 SSE 30s 重连，消息无重复无丢失 |
| F12 | 时间旅行：回到第 1 轮 fork，新分支消息带 fork_parent，旧分支消息仍可查 |
| F13 | 法官输出非法 next（如 "ghost_agent"）→ 该轮被过滤+反馈重调；连续 2 次非法 → conclude，全程无异常栈 |
| F10（保留） | ENABLE_KAFKA=false 时以上全部在单进程通过（checkpoint 仍在 PG） |

---

## 8. 任务修订（相对前序规格 §8）

**P0 增补**
- T0.9 引入 `AsyncPostgresSaver`（依赖 + setup + 健康检查 + 连接串）；建 `collab_turns`、`host_decisions` 表。

**P1 重构（替换原 T1.3/T1.4/T1.5）**
- T1.3′ `build_collab_graph()`：星型图注册（prepare/host/agent 节点工厂×注册表/tool 节点/ask_user/conclude）+ 固定回身边 + 节点工厂按 agent_id 绑定 Skill（零侵入映射入参）。
- T1.4′ HostSkill：双输出（口语发言 + directive JSON）、JSON 容错提取、白名单/轮次校验与反馈重调、host_decisions 审计落库。
- T1.5′ 恢复引擎：turn 执行器（Kafka/进程内双模式共用）含状态机、租约心跳、幂等 event_key、resume API、checkpoint 列表/fork API；SSE 与 checkpoint 联动（interrupted 卡片、续跑状态条）。
- T1.6′ court 模板配置化（host=judge、roster、verdict 节点绑定 JudgmentReportSkill）；旧 workflow 仅保留维护。
- 前端 T1.8 增补：回合时间线（含法官"为什么这样安排"的 reason 展示）、待补证卡片、失败重试按钮、"回到此轮重审"入口。

**文档**：本规格 + 前序规格冲突处以本文为准；CODE_WIKI 更新多智能体章节时以新星型图为准。

---

## 9. 风险与对策（新增）

1. **LLM 调度死循环/偏心** → max_rounds 硬顶 + 每轮 host_decisions 审计 + 提示词决策树；后续可加"主持人决策质量"离线评估。
2. **checkpoint 膨胀** → PG 定期任务：completed turn 的 checkpoint 保留 30 天后清理（消息正文已在 messages 表，checkpoint 仅为续跑）；fork 链保留 90 天。
3. **动态图与多 worker 并发写同一 thread** → LangGraph checkpoint 乐观并发（thread+checkpoint 版本）+ Redis 锁；冲突方重新读最新 checkpoint 再续。
4. **主持人和 Agent 模型成本** → host 每 spoke 都被调起，调用次数 ≈ 发言数×2：host 用 flash 模型做 directive（结构化小输出），仅关键节点（开庭/裁决）用 pro；普通会商默认 max_rounds=2 控制总量。
5. **LangGraph 版本管理** → requirements 锁定 `langgraph>=1.2,<2`、`langgraph-checkpoint-postgres` 兼容版本，避免 0.2 旧声明误装。
