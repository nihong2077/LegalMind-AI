<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,6&height=200&section=header&text=⚖️%20LegalMind%20AI&fontSize=64&fontAlignY=35&animation=fadeIn" alt="header" />

<p>
  <img src="https://img.shields.io/github/stars/nihong2077/LegalMind-AI?style=for-the-badge&logo=github&color=f1c40f" alt="Stars">
  <img src="https://img.shields.io/github/forks/nihong2077/LegalMind-AI?style=for-the-badge&logo=github&color=3498db" alt="Forks">
  <img src="https://img.shields.io/github/last-commit/nihong2077/LegalMind-AI?style=for-the-badge&color=2ecc71" alt="Last Commit">
  <img src="https://img.shields.io/github/license/nihong2077/LegalMind-AI?style=for-the-badge&color=9b59b6" alt="License">
</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.135%2B-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=nextdotjs&logoColor=white" alt="Next.js">
  <img src="https://img.shields.io/badge/TypeScript-5%2B-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/LangGraph-Multi--Agent-2F80ED?style=flat-square&logo=langchain&logoColor=white" alt="LangGraph">
  <br>
  <img src="https://img.shields.io/badge/Qdrant-Vector_DB-FF4F64?style=flat-square&logo=qdrant&logoColor=white" alt="Qdrant">
  <img src="https://img.shields.io/badge/DeepSeek-V4-4B32C3?style=flat-square&logo=openai&logoColor=white" alt="DeepSeek">
  <img src="https://img.shields.io/badge/PostgreSQL_16-pgvector-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/LiteLLM-Proxy-1C3C3C?style=flat-square" alt="LiteLLM">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
</p>

<h3>An intelligent legal workbench powered by LangGraph multi-agent orchestration and hybrid RAG retrieval</h3>

<p>
  🏛️ <b>Courtroom Simulation</b> &nbsp;·&nbsp;
  📄 <b>Contract Review</b> &nbsp;·&nbsp;
  🔍 <b>Legal Knowledge Retrieval</b> &nbsp;·&nbsp;
  🧠 <b>Long-term Memory</b> &nbsp;·&nbsp;
  🌐 <b>Web Search</b>
</p>

<p>
  <sub>Explainable · Traceable · Stream-interactive AI legal assistant</sub>
</p>

<p>
  <a href="#english"><b>English</b></a> &nbsp;|&nbsp; <a href="#简体中文"><b>简体中文</b></a>
</p>

<br>

---

</div>

> [!IMPORTANT]
> **AI-assisted position** — This project is an AI assistance tool and does **not** replace the professional judgment of lawyers or judicial authorities. All output is for learning, research and demonstration purposes only. Any decision or consequence arising from the use of this system shall be borne by the user.

---

# English

## Table of Contents

- [Overview](#overview)
- [Feature Highlights](#feature-highlights)
- [Architecture](#architecture)
- [Agent Roster & Collaboration Templates](#agent-roster--collaboration-templates)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Knowledge Base Import](#knowledge-base-import)
- [Collaboration Turn Lifecycle](#collaboration-turn-lifecycle)
- [API Overview](#api-overview)
- [Observability & Health Probes](#observability--health-probes)
- [Reliability & Graceful Degradation](#reliability--graceful-degradation)
- [Security & Key Isolation](#security--key-isolation)
- [Testing](#testing)
- [Documentation Map](#documentation-map)
- [Roadmap](#roadmap)
- [License & Disclaimer](#license--disclaimer)

## Overview

LegalMind AI is a research-grade **multi-agent legal collaboration platform**. Unlike a single-chatbot design, it runs a **star-topology LangGraph graph**: a hidden host/scheduler node decides *who speaks next* and *whether the round continues*, while each participating agent is an independent spoke that keeps its own persona and streaming method.

Key ideas:

- **Data-driven orchestration** — agents, rosters and templates live in the database (`agent_registry`, `case_roster_templates`). Business order is never hard-coded into graph edges; the graph only enforces guardrails.
- **Zero-invasive skill adaptation** — group-chat context is mapped onto each skill's existing streaming entry point without rewriting any persona prompt.
- **Explainability first** — one graph serves every template; the same compiled graph is dispatched at runtime by `state.case_type`.

## Feature Highlights

| | Capability | What it does |
|---|---|---|
| 🏛️ | **Multi-agent collaboration** | Group chat / consultation with 10 registered agents; a hidden scheduler controls speaking order. Courtroom template is judged by the *judge* agent, and a **neutral centered notice** ("下面是 X 发言") is the only user-visible turn indicator. |
| 📄 | **Contract review** | Upload PDF / Word / TXT, parse, extract clauses, scan risks, and produce a structured review report with side-by-side original text. |
| 🔍 | **Hybrid RAG retrieval** | Dense vector + sparse keyword recall across Qdrant and pgvector, merged, deduplicated, then reranked; results injected as a **separate system message** (never overwriting the persona prompt). |
| 🧠 | **Long-term memory** | Per-user memory extraction (Flash model), PostgreSQL `memories` table as source of truth, Qdrant `user_memories` (1024 / Cosine) for vector recall; similarity ≥ 0.90 merges, 0.75–0.90 raises a warning instead of silently merging. |
| 🌐 | **Web search (DeepSeek Search/Fetch)** | Before speaking, an agent decides with its own model whether it needs the web; if yes it calls DeepSeek Search/Fetch and injects a `【联网检索资料】` block plus a citation card. |
| 🧾 | **Citation cards** | Law citations, case citations and web citations are persisted as `msg_type=card` with structured `metadata.citations` and rendered as blue-bordered cards. |
| 🛡️ | **Engineering resilience** | Checkpoint-based interrupt/resume, turn fork & time-travel, idempotent message writes via `event_key`, Redis circuit breakers, and full graceful degradation when Kafka/Redis/LLM are unavailable. |
| 📊 | **Observability** | OpenTelemetry traces exported to Jaeger, Prometheus `/metrics`, separated `/healthz` (never touches dependencies) and `/readyz` (parallel dependency checks). |

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        🌐  Frontend (Next.js 14)                 │
│      App Router · React 18 · Zustand · Tailwind · SSE client     │
└──────────────────────────────┬───────────────────────────────────┘
                               │  HTTP / SSE (Bearer JWT)
┌──────────────────────────────▼───────────────────────────────────┐
│                     ⚙️  FastAPI Gateway  (:8000)                 │
│  /api  ·  /api/conversations  ·  /api/collab/conversations        │
│  /api/agents  ·  /api/memories  ·  /metrics  ·  /healthz         │
├──────────────────────────────────────────────────────────────────┤
│  🕸️  LangGraph Star Topology (one compiled graph, all templates) │
│      hidden host/scheduler ──► agent spokes ──► tool spokes       │
│      (no user-facing bubble)     (persona skills)  (RAG workers)  │
└──────┬───────────────┬───────────────────┬───────────────────────┘
       │               │                   │
 ┌─────▼─────┐  ┌──────▼───────┐   ┌───────▼────────┐
 │  Redis 7  │  │ PostgreSQL 16│   │  Qdrant v1.9   │
 │ cache/queue│ │  + pgvector  │   │ vector store   │
 └───────────┘  │  4 databases │   └────────────────┘
                └──────────────┘
       │
 ┌─────▼────────────────────────────────────────────┐
 │  🧠 LiteLLM Proxy (:4000) — single model gateway │
 │     deepseek-v4-pro · deepseek-flash · fallback  │
 │     Search/Fetch pass-through (real key injected)│
 └──────────────────────────────────────────────────┘
```

Supporting services (Docker Compose): Jaeger (OTel traces), Kafka 3.7.2 KRaft (optional event bus) and three worker roles (`collab`, `memory`, `doc`) sharing the backend image.

## Agent Roster & Collaboration Templates

**10 registered agents** (seeded by [05-seed-agents-templates.sql](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/sql/init/05-seed-agents-templates.sql)):

| agent_id | Name | Role | Type |
|---|---|---|---|
| `general_assistant` | 法律助手 | General Q&A (default single-chat agent) | Agent |
| `legal_analyst` | 法务分析师 | Case analysis & issue framing | Agent |
| `contract_reviewer` | 合同顾问 | Contract clause risk review | Agent |
| `legal_researcher` | 法规检索员 | Statute retrieval (law domain) | Tool |
| `case_searcher` | 类案检索员 | Case-law retrieval (judge domain) | Tool |
| `mediator` | 调解员 | Mediation; default host of generic templates | Agent |
| `plaintiff_lawyer` | 原告律师 | Claimant representation | Agent |
| `defense_lawyer` | 被告律师 | Respondent defense | Agent |
| `judge` | 法官 | Courtroom host & final judgment | Agent |
| `clerk` | 书记员 | Minutes & legal document drafts | Agent |

**8 collaboration templates** (`case_roster_templates`): `contract`, `labor`, `marriage`, `tort`, `debt`, `realestate`, `court` (adapter `court`), `custom`. Tool agents are prefetched in parallel at the start of each round and never occupy a serial speaking slot.

## Tech Stack

**Backend** — FastAPI + Uvicorn · SSE via `sse-starlette` · LangGraph 1.x + `langgraph-checkpoint-postgres` (interrupt / resume / fork) · Pydantic v2 Settings · PyJWT · SQLAlchemy 2.0 (asyncpg) · aiokafka · structlog · tenacity · OpenTelemetry · prometheus-client · PyMuPDF / python-docx · sentence-transformers (Qwen3-Embedding / Qwen3-Reranker) · PaddleOCR.

**Frontend** — Next.js 14 App Router · React 18 · TypeScript · Zustand · Tailwind CSS · lucide-react · framer-motion.

**Infrastructure** — PostgreSQL 16 + pgvector · Qdrant v1.9 · Redis 7 (AOF, LRU) · LiteLLM Proxy · Kafka 3.7.2 (KRaft, optional) · Jaeger all-in-one · Docker Compose.

**Models** — `deepseek-v4-pro` (heavy analysis / contract review) and `deepseek-flash` (fast retrieval / light tasks / memory extraction), with automatic cross-fallback configured in [litellm/config.yaml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/litellm/config.yaml).

## Project Structure

```
LegalMind AI/
├── backend/                          # 🐍 FastAPI service
│   ├── app/
│   │   ├── main.py                   #   app entry, lifecycle, health, metrics
│   │   ├── core/                     #   config, security, users, redis/pg/qdrant,
│   │   │                             #   embedding, reranker, llm_client, web_search
│   │   ├── routers/                  #   gateway, conversations, collab, agents, memory
│   │   ├── services/
│   │   │   ├── collab/               #   LangGraph star topology, scheduler, tools,
│   │   │   │                         #   speaker notice, web decision, templates
│   │   │   ├── legal/                #   RAG retriever, BM25, rerank, KFE
│   │   │   ├── memory/               #   long-term memory store & pipeline
│   │   │   └── agents/ workflows/    #   skill wrappers, legacy workflows
│   │   ├── worker/                   #   collab / memory / doc worker entrypoints
│   │   └── sql/init/                 #   Postgres bootstrap + seed data
│   ├── tests/                        #   33 test modules (pytest + pytest-asyncio)
│   ├── scripts/                      #   data cleaning & knowledge import
│   └── requirements.txt / Dockerfile
├── frontend/                         # ⚛️ Next.js 14 workspace
│   ├── app/                          #   chat, court, documents, knowledge,
│   │                                 #   cases, dashboard, messages, login
│   ├── components/                   #   chat & collab UI, citation cards
│   ├── store/                        #   Zustand stores
│   └── package.json / Dockerfile
├── litellm/config.yaml               # 🧠 model gateway + Search/Fetch pass-through
├── docker-compose.yml                # 🐳 full orchestration
├── deploy/                           # 🚀 simplified deployment config
├── scripts/setup_local_model.sh      # 🖥️ local fine-tuned model bootstrap
├── docs/                             # 📚 specs & delivery records
└── CODE_WIKI.md                      # 📖 in-depth code walkthrough
```

## Quick Start

### Requirements

| Dependency | Minimum | Notes |
|---|:---:|---|
| Python | `≥ 3.10` | Backend runtime |
| Node.js | `≥ 18` | Frontend runtime |
| Docker | `≥ 24` | Infrastructure containers |
| CUDA | `≥ 11.8` | GPU inference (optional, falls back to CPU) |

### 1. Clone & configure

```bash
git clone https://github.com/nihong2077/LegalMind-AI.git
cd LegalMind-AI
cp .env.example .env          # then fill in real secrets
```

### 2. Start infrastructure

```bash
docker compose up -d redis postgres qdrant litellm-db litellm
docker compose ps             # wait until all are healthy
```

### 3. Start the backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> Swagger UI: <http://localhost:8000/docs> · Health: <http://localhost:8000/healthz>

### 4. Start the frontend

```bash
cd frontend
npm install && npm run dev
```

> Workbench: <http://localhost:3000>

### One-shot deployment (Docker)

```bash
docker compose up -d --build
docker compose logs -f --tail=50
```

## Environment Variables

| Variable | Required | Purpose |
|---|:---:|---|
| `JWT_SECRET_KEY` | ✅ | JWT signing key (`openssl rand -hex 32`) |
| `REDIS_URL` | ✅ | Redis connection (sessions, cache, queues) |
| `PG_JUDGE_URL` / `PG_LAWYER_URL` / `PG_LAW_URL` / `PG_APP_URL` | ✅ | The three knowledge databases + `legalmind_app` application database |
| `DEEPSEEK_API_KEY` | ✅ | **Consumed by LiteLLM only** — never injected into the API container |
| `LITELLM_MASTER_KEY` / `LITELLM_VIRTUAL_KEY` / `LITELLM_DB_PASSWORD` | ✅ | LiteLLM proxy auth, virtual key used by the backend |
| `WEB_SEARCH_ENABLED` / `WEB_SEARCH_TOP_N` / `WEB_SEARCH_TIMEOUT` / `WEB_SEARCH_MAX_ATTEMPTS` | — | Web search toggle and tuning |
| `ENABLE_KAFKA` | — | `false` (default) = in-process event bus; `true` = lazy-connect Kafka with auto-degrade |
| `OTEL_ENABLED` / `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Tracing toggle and Jaeger endpoint (enabled by default) |
| `LOG_FORMAT` / `LOG_LEVEL` | — | `json` for production, `console` for local |
| `OCR_API_URL` / `OCR_API_TOKEN` / `OCR_MODEL` | — | PaddleOCR async job service |

## Knowledge Base Import

```bash
cd backend && source venv/bin/activate

python scripts/import_all.py --resume         # full import, resumable
python scripts/import_all.py --verify-only    # verify only
python scripts/import_all.py --resume --skip-lawyer
```

Pipeline: `clean text → chunk → embed → upsert into Qdrant → record checkpoint`.

> [!TIP]
> Large corpora are excluded from Git. Prepare the files under `data/` yourself; the importer resumes from the last checkpoint after an interruption.

## Collaboration Turn Lifecycle

1. **Turn creation** — a message creates a `turn`; existing open turns are resumed, running/locked turns return error `50901`.
2. **Round start** — tool agents are prefetched in parallel; the hidden scheduler picks the next speaker.
3. **Web pre-decision** — the speaking agent may call DeepSeek Search/Fetch (see web search above) and merge the material block into its context.
4. **Streaming speech** — the skill streams token by token over SSE, persisted idempotently with `message_id = uuid5(event_key)` and `INSERT ... ON CONFLICT DO NOTHING`.
5. **Speaker notice** — a neutral, background-free centered line (`metadata.kind="speaker_notice"`) marks each turn boundary.
6. **Convergence** — the scheduler decides whether to continue; the court template always ends with a verdict from the **judge**.
7. **Minutes & audit** — the clerk produces minutes; host decisions are written to `host_decisions` for audit.
8. **Fork / time-travel** — any turn can be branched via the checkpoint/fork endpoints.

## API Overview

| Endpoint | Method | Auth | Description |
|---|---|:---:|:---:|---|
| `/api/auth/register` | `POST` | — | Register a user |
| `/api/auth/token` | `POST` | — | Login, returns JWT |
| `/api/chat/stream` | `SSE` | 🔑 | Streaming legal consultation |
| `/api/agents/stream` · `/api/agents/run` | `POST` | 🔑 | Run a single agent (stream / sync) |
| `/api/knowledge/search` · `/api/knowledge/list` | `POST` / `GET` | 🔑 | Hybrid legal knowledge retrieval |
| `/api/documents/upload` · `/api/documents/{id}/content` · `/api/documents/{id}/analyze` | `POST` / `GET` | 🔑 | Document upload, parsed content, analysis |
| `/api/contract/review` · `/api/contract/review/stream` · `/api/contract/draft-clause` | `POST` | 🔑 | Contract review & clause drafting |
| `/api/conversations` | `GET` / `POST` | 🔑 | List / create collaboration conversations |
| `/api/conversations/{id}/members` · `/my_role` | `POST` / `DELETE` | 🔑 | Manage members; user role takeover |
| `/api/conversations/{id}/messages` · `/minutes` | `GET` / `POST` | 🔑 | Messages and meeting minutes |
| `/api/conversations/{id}/turns/{turn_id}/checkpoints` · `/fork` | `GET` / `POST` | 🔑 | Turn checkpoints and state branching |
| `/api/collab/conversations/{id}/events` · `/events/ticket` | `GET` / `POST` | 🔑 | SSE event stream + one-time ticket |
| `/api/agents` · `/api/agents/templates` | `GET` | 🔑 | Agent registry and templates |
| `/api/memories` (+`/{id}`, `/setting`) | `GET`/`POST`/`PATCH`/`DELETE`/`PUT` | 🔑 | Long-term memory CRUD, filtering, per-user toggle |
| `/health` · `/healthz` · `/readyz` · `/metrics` | `GET` | — | Liveness, readiness and Prometheus metrics |

All `/api/*` responses are wrapped in a unified envelope `{code, message, data, request_id}`.

## Observability & Health Probes

- **Tracing** — OpenTelemetry instrumentation for FastAPI, HTTPX, SQLAlchemy and Redis, exported over OTLP gRPC to Jaeger (<http://localhost:16686>). Tracing is always on; if Jaeger is down only traces are lost.
- **Metrics** — `/metrics` exposes Prometheus metrics with low-cardinality route-template labels plus domain metrics (web-search calls, memory ingestion, turn results).
- **Probes** — `/healthz` never checks external dependencies (always `200`); `/readyz` aggregates parallel dependency checks with per-component timeouts and failure isolation.

## Reliability & Graceful Degradation

- **Idempotency** — every group-chat message carries a unique `event_key` (`{turn_id}:r{round}:{key}:{seq}`); writes use `INSERT ... ON CONFLICT DO NOTHING` and the record is fetched before it is emitted, so replays never duplicate content.
- **Poison-message isolation** — the collab and memory consumers isolate each message, and exhausted retries are routed to `collab-turns-dlq` / `memory-events-dlq` instead of blocking the queue.
- **Kafka optional** — with `ENABLE_KAFKA=false` the event bus falls back to in-process execution, so local development needs no broker.
- **Circuit breakers & fallback** — per-service Redis circuit breakers fail *open*; LLM streaming retries are only allowed before the first byte to avoid duplicate generation and billing; unavailable models fall back to `deepseek-flash` with an SSE `status` notice.
- **Guardrails over logic** — the graph only enforces guardrails; any scheduler exception falls back to the template's default order instead of aborting the round.

## Security & Key Isolation

- **LLM keys never reach the backend** — the API container only holds a LiteLLM *virtual key*; real provider keys are injected inside the LiteLLM proxy via `os.environ/DEEPSEEK_API_KEY`. Web Search/Fetch are exposed as LiteLLM `pass_through_endpoints`, so the real key never leaves the proxy.
- **Auth** — JWT with the username in the `sub` claim; separate register and login endpoints; passwords hashed with `hashlib.pbkdf2_hmac` and verified with `hmac.compare_digest`.
- **User isolation** — every frontend `localStorage` key and backend Redis key is namespaced by username; the application database (`legalmind_app`) is kept separate from the knowledge databases to avoid cross-database table pollution.
- **Secret hygiene** — `.env`, `litellm/secrets.yaml`, model files and uploads are git-ignored; only `.env.example` templates are committed.

## Testing

```bash
cd backend && source venv/bin/activate
pytest            # 33 test modules
```

Latest full run: **334 passed**. Suites cover the API envelope, auth, RAG retriever (dense/sparse merge and payload-content resolution), LangGraph topology, scheduler/host dispatch, tool spokes, speaker notice, web-search client and web pre-decision, memory pipeline, and worker DLQ routing.

## Documentation Map

| Doc | Content |
|---|---|
| [CODE_WIKI.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/CODE_WIKI.md) | In-depth code walkthrough (architecture, modules, storage, conventions) |
| [collab-implementation_plan.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-implementation_plan.md) | Collaboration deliverables & task tracking |
| [collab-scheduling_spec.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-scheduling_spec.md) | Host/scheduler specification |
| [collab-supervisor-checkpoint_spec.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-supervisor-checkpoint_spec.md) | Checkpoint, interrupt/resume and fork |
| [collab-ui-refactor_plan.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-ui-refactor_plan.md) | Collaboration UI refactor plan |

## Roadmap

- [x] Harness engineering: unified envelope, structured logs, OTel tracing, circuit breakers, health probes
- [x] Star-topology multi-agent collaboration with a hidden host/scheduler
- [x] Tool spokes with law/case citation cards prefetched per round
- [x] Long-term memory (store, worker, recall, per-user toggle)
- [x] Web search (DeepSeek Search/Fetch) with pre-decision and citation cards
- [ ] Memory page UI for the 0.75–0.90 similarity warning channel
- [ ] Conservative tuning of the judge-domain recall threshold so case-law spokes never return empty
- [ ] Multi-node Kafka cluster and horizontal worker scaling

## License & Disclaimer

Released under the [MIT License](LICENSE).

This project is intended for **learning, research, competition demonstration and legal-AI engineering practice**. Its output **does not constitute legal advice, lawyer's opinion or judicial conclusion**. Any decision or consequence arising from the use of this system shall be borne by the user.

---

# 简体中文

## 目录

- [项目概览](#项目概览)
- [功能亮点](#功能亮点)
- [系统架构](#系统架构)
- [Agent 名册与协作模板](#agent-名册与协作模板)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [法律知识库导入](#法律知识库导入)
- [协作轮次生命周期](#协作轮次生命周期)
- [API 概览](#api-概览)
- [可观测性与健康探针](#可观测性与健康探针)
- [工程韧性与优雅降级](#工程韧性与优雅降级)
- [安全与密钥隔离](#安全与密钥隔离)
- [测试](#测试)
- [文档地图](#文档地图)
- [路线图](#路线图)
- [许可证与免责声明](#许可证与免责声明)

## 项目概览

LegalMind AI 是一个研究级的**多智能体法律协作平台**。它采用**星型拓扑 LangGraph 图**：由隐藏的主持/调度节点决定*下一位发言者*与*本轮是否继续*，每个参与 Agent 作为独立辐条保留自己的人设 prompt 与流式方法。

核心设计：

- **数据驱动编排** —— Agent、名册与模板存于数据库（`agent_registry`、`case_roster_templates`），业务顺序从不硬编码为图的固定边，图只提供护栏。
- **零侵入 Skill 适配** —— 群上下文被映射到既有 Skill 的流式入参，不修改任何人设 prompt。
- **可解释优先** —— 一张编译图服务所有模板，运行时按 `state.case_type` 分派。

## 功能亮点

| | 能力 | 说明 |
|---|---|---|
| 🏛️ | **多智能体协作** | 10 个注册 Agent 的群聊/会商；发言顺序由隐藏调度智能体控制。模拟庭审模板由**法官**作出最终判决，用户侧仅能看到中性居中的「下面是 X 发言」轮次提示。 |
| 📄 | **合同智能审查** | 支持 PDF / Word / TXT 上传解析、条款提取、风险扫描，产出结构化审查报告并支持原文对照。 |
| 🔍 | **RAG 混合检索** | 在 Qdrant 与 pgvector 上并行做稠密向量 + 稀疏关键词召回，合并去重后精排；检索结果以**独立 system 消息**注入，绝不覆盖人设提示词。 |
| 🧠 | **长期记忆** | 按用户抽取记忆（Flash 模型），PostgreSQL `memories` 表为事实源，Qdrant `user_memories`（1024 / Cosine）负责向量召回；相似度 ≥ 0.90 合并，0.75–0.90 只告警不静默合并。 |
| 🌐 | **联网检索（DeepSeek Search/Fetch）** | 发言前由 Agent 用自身模型判断是否需要联网；需要则调用 DeepSeek Search/Fetch，注入 `【联网检索资料】` 资料块并产出引用卡。 |
| 🧾 | **引用卡** | 法规引用、类案引用与联网引用以 `msg_type=card` 落库，携带结构化 `metadata.citations`，前端渲染为蓝边卡片。 |
| 🛡️ | **工程韧性** | 基于 checkpointer 的中断恢复、轮次分叉与时间旅行、`event_key` 幂等写入、Redis 熔断器，以及 Kafka/Redis/LLM 不可用时的完整降级。 |
| 📊 | **可观测性** | OpenTelemetry trace 导出 Jaeger、Prometheus `/metrics`、严格区分 `/healthz`（不探外部依赖）与 `/readyz`（并行依赖检查）。 |

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        🌐  前端（Next.js 14）                     │
│      App Router · React 18 · Zustand · Tailwind · SSE 客户端      │
└──────────────────────────────┬───────────────────────────────────┘
                               │  HTTP / SSE（Bearer JWT）
┌──────────────────────────────▼───────────────────────────────────┐
│                     ⚙️  FastAPI 网关  (:8000)                    │
│  /api  ·  /api/conversations  ·  /api/collab/conversations        │
│  /api/agents  ·  /api/memories  ·  /metrics  ·  /healthz         │
├──────────────────────────────────────────────────────────────────┤
│  🕸️  LangGraph 星型拓扑（一张编译图服务全部模板）                  │
│      隐藏主持/调度 ──► Agent 辐条 ──► 工具辐条                     │
│      （无用户可见气泡）   （人设 Skill）    （RAG 检索）            │
└──────┬───────────────┬───────────────────┬───────────────────────┘
       │               │                   │
 ┌─────▼─────┐  ┌──────▼───────┐   ┌───────▼────────┐
 │  Redis 7  │  │ PostgreSQL 16│   │  Qdrant v1.9   │
 │ 缓存/队列  │  │  + pgvector  │   │   向量检索库    │
 └───────────┘  │   四库架构    │   └────────────────┘
                └──────────────┘
       │
 ┌─────▼────────────────────────────────────────────┐
 │  🧠 LiteLLM Proxy (:4000) —— 统一模型网关         │
 │     deepseek-v4-pro · deepseek-flash · 自动回退    │
 │     Search/Fetch 透传（代理侧注入真实 key）        │
 └──────────────────────────────────────────────────┘
```

辅助服务（Docker Compose）：Jaeger（OTel trace）、Kafka 3.7.2 KRaft（可选事件总线），以及复用后端镜像的三个 worker 角色（`collab` / `memory` / `doc`）。

## Agent 名册与协作模板

**10 个注册 Agent**（种子数据见 [05-seed-agents-templates.sql](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/sql/init/05-seed-agents-templates.sql)）：

| agent_id | 名称 | 职责 | 类型 |
|---|---|---|---|
| `general_assistant` | 法律助手 | 通用法律问答（单聊默认 Agent） | Agent |
| `legal_analyst` | 法务分析师 | 案情梳理、法律关系与争点归纳 | Agent |
| `contract_reviewer` | 合同顾问 | 合同条款风险审查与修改建议 | Agent |
| `legal_researcher` | 法规检索员 | 现行法规检索（law 域） | 工具 |
| `case_searcher` | 类案检索员 | 裁判文书/类案检索（judge 域） | 工具 |
| `mediator` | 调解员 | 调解主持；通用模板默认主持人 | Agent |
| `plaintiff_lawyer` | 原告律师 | 原告方主张与证据组织 | Agent |
| `defense_lawyer` | 被告律师 | 被告方答辩与质证 | Agent |
| `judge` | 法官 | 庭审主持与最终判决 | Agent |
| `clerk` | 书记员 | 会商纪要与文书草稿 | Agent |

**8 个协作模板**（`case_roster_templates`）：`contract`、`labor`、`marriage`、`tort`、`debt`、`realestate`、`court`（adapter 为 `court`）、`custom`。工具型 Agent 每轮开始时并行预取，不占串行发言位。

## 技术栈

**后端** —— FastAPI + Uvicorn · `sse-starlette` · LangGraph 1.x + `langgraph-checkpoint-postgres`（中断/恢复/分叉）· Pydantic v2 Settings · PyJWT · SQLAlchemy 2.0（asyncpg）· aiokafka · structlog · tenacity · OpenTelemetry · prometheus-client · PyMuPDF / python-docx · sentence-transformers（Qwen3-Embedding / Qwen3-Reranker）· PaddleOCR。

**前端** —— Next.js 14 App Router · React 18 · TypeScript · Zustand · Tailwind CSS · lucide-react · framer-motion。

**基础设施** —— PostgreSQL 16 + pgvector · Qdrant v1.9 · Redis 7（AOF + LRU）· LiteLLM Proxy · Kafka 3.7.2（KRaft，可选）· Jaeger all-in-one · Docker Compose。

**模型** —— `deepseek-v4-pro`（重型分析/合同审查）与 `deepseek-flash`（快速检索/轻量任务/记忆抽取），双向自动回退配置见 [litellm/config.yaml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/litellm/config.yaml)。

## 项目结构

```
LegalMind AI/
├── backend/                          # 🐍 FastAPI 服务
│   ├── app/
│   │   ├── main.py                   #   入口、生命周期、健康检查、指标
│   │   ├── core/                     #   配置、鉴权、用户、redis/pg/qdrant、
│   │   │                             #   embedding、reranker、llm_client、web_search
│   │   ├── routers/                  #   gateway、conversations、collab、agents、memory
│   │   ├── services/
│   │   │   ├── collab/               #   LangGraph 星型拓扑、调度、工具辐条、
│   │   │   │                         #   轮次分隔条、联网前置决策、模板
│   │   │   ├── legal/                #   RAG 检索、BM25、精排、KFE
│   │   │   ├── memory/               #   长期记忆存储与流水线
│   │   │   └── agents/ workflows/    #   Skill 封装与既有工作流
│   │   ├── worker/                   #   collab / memory / doc worker 入口
│   │   └── sql/init/                 #   Postgres 建库 + 种子数据
│   ├── tests/                        #   33 个测试模块（pytest + pytest-asyncio）
│   ├── scripts/                      #   数据清洗与知识库导入
│   └── requirements.txt / Dockerfile
├── frontend/                         # ⚛️ Next.js 14 工作台
│   ├── app/                          #   chat、court、documents、knowledge、
│   │                                 #   cases、dashboard、messages、login
│   ├── components/                   #   对话与协作 UI、引用卡
│   ├── store/                        #   Zustand 状态
│   └── package.json / Dockerfile
├── litellm/config.yaml               # 🧠 模型网关 + Search/Fetch 透传
├── docker-compose.yml                # 🐳 完整编排
├── deploy/                           # 🚀 简化部署配置
├── scripts/setup_local_model.sh      # 🖥️ 本地微调模型初始化
├── docs/                             # 📚 规格与交付记录
└── CODE_WIKI.md                      # 📖 深度代码导读
```

## 快速开始

### 环境要求

| 依赖 | 最低版本 | 说明 |
|------|:--------:|------|
| Python | `≥ 3.10` | 后端运行时 |
| Node.js | `≥ 18` | 前端运行时 |
| Docker | `≥ 24` | 基础设施容器化 |
| CUDA | `≥ 11.8` | GPU 推理（可选，缺失自动回退 CPU） |

### 1. 克隆与配置

```bash
git clone https://github.com/nihong2077/LegalMind-AI.git
cd LegalMind-AI
cp .env.example .env          # 填入真实密钥
```

### 2. 启动基础设施

```bash
docker compose up -d redis postgres qdrant litellm-db litellm
docker compose ps             # 等待全部 healthy
```

### 3. 启动后端

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> Swagger UI：<http://localhost:8000/docs>　·　健康检查：<http://localhost:8000/healthz>

### 4. 启动前端

```bash
cd frontend
npm install && npm run dev
```

> 工作台：<http://localhost:3000>

### 一键部署（Docker）

```bash
docker compose up -d --build
docker compose logs -f --tail=50
```

## 环境变量

| 变量 | 必填 | 用途 |
|---|:---:|---|
| `JWT_SECRET_KEY` | ✅ | JWT 签名密钥（`openssl rand -hex 32`） |
| `REDIS_URL` | ✅ | Redis 连接（会话、缓存、队列） |
| `PG_JUDGE_URL` / `PG_LAWYER_URL` / `PG_LAW_URL` / `PG_APP_URL` | ✅ | 三知识库 + `legalmind_app` 应用库 |
| `DEEPSEEK_API_KEY` | ✅ | **仅由 LiteLLM 消费**，绝不注入后端 API 容器 |
| `LITELLM_MASTER_KEY` / `LITELLM_VIRTUAL_KEY` / `LITELLM_DB_PASSWORD` | ✅ | LiteLLM 代理鉴权；后端只持有虚拟 key |
| `WEB_SEARCH_ENABLED` / `WEB_SEARCH_TOP_N` / `WEB_SEARCH_TIMEOUT` / `WEB_SEARCH_MAX_ATTEMPTS` | — | 联网检索开关与调参 |
| `ENABLE_KAFKA` | — | `false`（默认）走进程内事件总线；`true` 懒连 Kafka 并自动降级 |
| `OTEL_ENABLED` / `OTEL_EXPORTER_OTLP_ENDPOINT` | — | trace 开关与 Jaeger 端点（默认开启） |
| `LOG_FORMAT` / `LOG_LEVEL` | — | 生产用 `json`，本地用 `console` |
| `OCR_API_URL` / `OCR_API_TOKEN` / `OCR_MODEL` | — | PaddleOCR 异步任务服务 |

## 法律知识库导入

```bash
cd backend && source venv/bin/activate

python scripts/import_all.py --resume         # 全量导入（断点续传）
python scripts/import_all.py --verify-only    # 仅校验
python scripts/import_all.py --resume --skip-lawyer
```

导入流程：`文本清洗 → 分段切片 → 向量嵌入 → 写入 Qdrant → 记录断点`。

> [!TIP]
> 大规模语料未包含在 Git 仓库中，请自行准备 `data/` 目录下的数据文件；导入脚本支持断点续传，中断后重跑会自动跳过已完成部分。

## 协作轮次生命周期

1. **轮次创建** —— 发送消息创建 `turn`；存在未完成轮次则续推，运行中/被他人锁定返回 `50901`。
2. **轮首预取** —— 工具型 Agent 并行预取；隐藏调度智能体选出下一位发言者。
3. **联网前置决策** —— 发言 Agent 可能调用 DeepSeek Search/Fetch，并把资料块并入上下文。
4. **流式发言** —— Skill 逐 token 经 SSE 输出，以 `message_id = uuid5(event_key)` + `INSERT ... ON CONFLICT DO NOTHING` 幂等落库。
5. **轮次分隔条** —— 无背景、小字居中的中性提示（`metadata.kind="speaker_notice"`）标记每轮边界。
6. **收敛判断** —— 调度智能体决定是否继续；庭审模板固定由**法官**作出最终判决。
7. **纪要与审计** —— 书记员产出会商纪要，主持人决策写入 `host_decisions` 供审计。
8. **分叉 / 时间旅行** —— 任意轮次可通过 checkpoint/fork 接口进行状态分支。

## API 概览

| 端点 | 方法 | 认证 | 说明 |
|---|---|:---:|:---:|---|
| `/api/auth/register` | `POST` | — | 用户注册 |
| `/api/auth/token` | `POST` | — | 登录获取 JWT |
| `/api/chat/stream` | `SSE` | 🔑 | 流式法律咨询 |
| `/api/agents/stream` · `/api/agents/run` | `POST` | 🔑 | 单 Agent 流式/同步执行 |
| `/api/knowledge/search` · `/api/knowledge/list` | `POST` / `GET` | 🔑 | 法律知识混合检索 |
| `/api/documents/upload` · `/api/documents/{id}/content` · `/api/documents/{id}/analyze` | `POST` / `GET` | 🔑 | 文档上传、解析内容、分析 |
| `/api/contract/review` · `/api/contract/review/stream` · `/api/contract/draft-clause` | `POST` | 🔑 | 合同审查与条款起草 |
| `/api/conversations` | `GET` / `POST` | 🔑 | 协作会话列表 / 创建 |
| `/api/conversations/{id}/members` · `/my_role` | `POST` / `DELETE` | 🔑 | 成员管理与用户角色接管 |
| `/api/conversations/{id}/messages` · `/minutes` | `GET` / `POST` | 🔑 | 消息与会商纪要 |
| `/api/conversations/{id}/turns/{turn_id}/checkpoints` · `/fork` | `GET` / `POST` | 🔑 | 轮次检查点与状态分叉 |
| `/api/collab/conversations/{id}/events` · `/events/ticket` | `GET` / `POST` | 🔑 | SSE 事件流 + 一次性票据 |
| `/api/agents` · `/api/agents/templates` | `GET` | 🔑 | Agent 注册表与模板 |
| `/api/memories`（含 `/{id}`、`/setting`） | `GET`/`POST`/`PATCH`/`DELETE`/`PUT` | 🔑 | 长期记忆 CRUD、筛选与按用户开关 |
| `/health` · `/healthz` · `/readyz` · `/metrics` | `GET` | — | 存活、就绪与 Prometheus 指标 |

全部 `/api/*` 响应统一包裹为 `{code, message, data, request_id}` 信封。

## 可观测性与健康探针

- **链路追踪** —— 对 FastAPI、HTTPX、SQLAlchemy、Redis 自动埋点，经 OTLP gRPC 导出至 Jaeger（<http://localhost:16686>）。追踪常开；Jaeger 宕机只丢 trace，不影响业务。
- **指标** —— `/metrics` 暴露低基数路由模板标签的 Prometheus 指标，并含领域指标（联网检索调用、记忆入库、轮次结果）。
- **探针** —— `/healthz` 不探任何外部依赖（恒返回 `200`）；`/readyz` 并行聚合依赖检查，逐组件超时并做失败隔离。

## 工程韧性与优雅降级

- **幂等** —— 每条群聊消息携带唯一 `event_key`（`{turn_id}:r{round}:{key}:{seq}`），写入用 `INSERT ... ON CONFLICT DO NOTHING`，且**先查库再下发**，重放不会产生重复内容。
- **毒消息隔离** —— collab 与 memory 消费者逐条隔离，重试耗尽后分别投递 `collab-turns-dlq` / `memory-events-dlq`，不阻塞整条队列。
- **Kafka 可选** —— `ENABLE_KAFKA=false` 时事件总线自动降级为进程内执行，本地开发无需 broker。
- **熔断与回退** —— 每个服务独立的 Redis 熔断器采用 fail-open；LLM 流式重试只允许发生在收到首字节之前，避免重复生成与重复计费；模型不可用时回退 `deepseek-flash` 并通过 SSE `status` 告知前端。
- **护栏而非逻辑** —— 图只提供护栏；调度异常时回退模板默认顺序，绝不中断整轮。

## 安全与密钥隔离

- **真实密钥不进后端** —— API 容器仅持有 LiteLLM **虚拟 key**；真实供应商 key 由 LiteLLM 代理侧的 `os.environ/DEEPSEEK_API_KEY` 注入。联网 Search/Fetch 以 LiteLLM `pass_through_endpoints` 暴露，真实 key 全程不离开代理。
- **鉴权** —— JWT 的 `sub` 携带用户名；注册与登录为独立端点；密码以 `hashlib.pbkdf2_hmac` 哈希，用 `hmac.compare_digest` 校验。
- **用户隔离** —— 前端 `localStorage` 与后端 Redis 的键均按用户名加命名空间；应用库（`legalmind_app`）与知识库分离，避免跨库表污染。
- **密钥卫生** —— `.env`、`litellm/secrets.yaml`、模型文件与上传目录均已 git-ignore，仓库仅保留 `.env.example` 模板。

## 测试

```bash
cd backend && source venv/bin/activate
pytest            # 33 个测试模块
```

最近一次全量结果：**334 passed**。覆盖 API 信封、鉴权、RAG 检索（稠密/稀疏合并与 payload 内容提升）、LangGraph 拓扑、调度与主持分派、工具辐条、轮次分隔条、联网检索客户端与前置决策、记忆流水线，以及 worker 的 DLQ 路由。

## 文档地图

| 文档 | 内容 |
|---|---|
| [CODE_WIKI.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/CODE_WIKI.md) | 深度代码导读（架构、模块、存储、约定） |
| [collab-implementation_plan.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-implementation_plan.md) | 协作功能交付与任务跟踪 |
| [collab-scheduling_spec.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-scheduling_spec.md) | 主持人/调度智能体规格 |
| [collab-supervisor-checkpoint_spec.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-supervisor-checkpoint_spec.md) | 检查点、中断恢复与分叉 |
| [collab-ui-refactor_plan.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-ui-refactor_plan.md) | 协作 UI 重构方案 |

## 路线图

- [x] Harness 工程化：统一信封、结构化日志、OTel 追踪、熔断器、健康探针
- [x] 星型拓扑多智能体协作 + 隐藏主持/调度智能体
- [x] 工具辐条与法规/类案引用卡（轮首并行预取）
- [x] 长期记忆（存储、worker、召回、按用户开关）
- [x] 联网检索（DeepSeek Search/Fetch）+ 前置决策 + 引用卡
- [ ] 记忆页 UI：承载 0.75–0.90 相似度提示通道
- [ ] 保守调优 judge 域召回阈值，避免类案辐条恒返回 0 条
- [ ] Kafka 多节点集群与 worker 水平扩展

## 许可证与免责声明

本项目采用 [MIT License](LICENSE)。

本项目仅用于 **学习、科研、竞赛展示** 与 **法律 AI 工程实践探索**。系统输出 **不构成法律意见、律师意见或司法结论**。因使用系统输出所产生的任何决策和后果，应由使用者自行承担。

---

<div align="center">

<br>

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,6&height=100&section=footer" alt="footer" />

<sub>Built with ❤️ by <b>LegalMind AI Team</b> &nbsp;|&nbsp; © 2025–2026</sub>

</div>
