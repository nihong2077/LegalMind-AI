# LegalMind AI - 智能法律助手

基于大语言模型的法律 AI 系统，集成**模拟法庭辩论**、**合同智能审查**、**法律知识检索**三大核心功能，采用 LangGraph 多智能体工作流 + RAG 混合检索架构。

## 功能概览

| 功能模块 | 说明 |
|---------|------|
| **模拟法庭** | 多角色辩论（原告/被告/法官/调解员），LangGraph 工作流驱动，SSE 实时流式输出 |
| **合同审查** | 上传 PDF/Word 合同 → AI 自动提取条款 → 风险扫描 → 生成结构化审查报告 |
| **法律知识库** | 97,000+ 法律法规 + 50,000+ 裁判文书，混合检索（Dense + Sparse + Rerank） |
| **智能对话** | 法律咨询对话，支持 SSE 流式响应，上下文感知 |

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js 14)                   │
│   Zustand 状态管理 │ SSE 流式对话 │ Tailwind CSS              │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / SSE
┌──────────────────────────────▼──────────────────────────────┐
│                     Backend (FastAPI)                         │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │  Gateway    │  │  LangGraph   │  │  RAG Retriever    │   │
│  │  (SSE/API)  │  │  Workflows   │  │  (Hybrid Search)  │   │
│  └────────────┘  └──────────────┘  └───────────────────┘   │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │  Security  │  │  Memory      │  │  Document Parser  │   │
│  │  (JWT)     │  │  Monitor     │  │  (PDF/Word/TXT)   │   │
│  └────────────┘  └──────────────┘  └───────────────────┘   │
└───────┬───────────────┬───────────────┬────────────────────┘
        │               │               │
   ┌────▼────┐   ┌──────▼──────┐  ┌─────▼─────┐
   │  Redis  │   │  PostgreSQL │  │  Qdrant   │
   │  Cache  │   │  + pgvector │  │  VectorDB │
   └─────────┘   └─────────────┘  └───────────┘
        │
   ┌────▼──────────────────────────────┐
   │  LiteLLM Proxy (多模型路由)        │
   │  → DeepSeek / vLLM 本地模型       │
   └────────────────────────────────────┘
```

## 技术栈

### 后端
- **Python 3.10+** | FastAPI | LangChain | LangGraph
- **Redis** 缓存 + 会话存储
- **PostgreSQL 16** + pgvector（结构化数据 + 向量检索）
- **Qdrant** 向量数据库（法律知识库）
- **LiteLLM** 多模型代理路由
- **PyMuPDF** PDF 解析 | **python-docx** Word 解析
- **Sentence-Transformers** (Qwen3-Embedding-0.6B) 文本嵌入
- **Prometheus** 监控指标

### 前端
- **Next.js 14** | React 18 | TypeScript
- **Zustand** 状态管理
- **Tailwind CSS** + Framer Motion
- **SSE** 流式对话（ReadableStream API）

### 基础设施
- **Docker Compose** 容器化部署（6 服务）
- **WSL2 Ubuntu** 开发环境

## 项目结构

```
LegalMind AI/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + lifespan + 内存监控
│   │   ├── core/              # 核心模块
│   │   │   ├── config.py      # 配置管理（pydantic-settings）
│   │   │   ├── security.py    # JWT 认证
│   │   │   ├── redis_client.py# Redis 连接池 + 重连
│   │   │   ├── pg_client.py   # PostgreSQL 异步连接
│   │   │   ├── qdrant_client.py# Qdrant 向量库
│   │   │   ├── llm_client.py  # LLM 客户端（直连 + LiteLLM 代理）
│   │   │   ├── embedding.py   # 嵌入模型加载
│   │   │   └── reranker.py    # 重排序模型
│   │   ├── routers/
│   │   │   └── gateway.py     # API 路由（SSE 流 + 文档管理）
│   │   ├── services/
│   │   │   ├── agents/        # 智能体技能
│   │   │   │   ├── plaintiff_skill.py   # 原告代理
│   │   │   │   ├── defendant_skill.py   # 被告代理
│   │   │   │   ├── judge_skill.py       # 法官代理
│   │   │   │   ├── mediator_skill.py    # 调解员代理
│   │   │   │   └── contract_reviewer.py # 合同审查员
│   │   │   ├── legal/         # 法律服务
│   │   │   │   ├── rag_retriever.py     # RAG 混合检索
│   │   │   │   ├── sparse_retriever.py  # BM25 稀疏检索
│   │   │   │   ├── kfe_extractor.py     # 关键事实提取
│   │   │   │   └── aux_nodes.py         # 辅助节点
│   │   │   └── workflows/     # LangGraph 工作流
│   │   │       ├── debate_workflow.py        # 模拟法庭辩论
│   │   │       ├── contract_review_workflow.py# 合同审查
│   │   │       └── legal_workflow.py         # 法律咨询
│   │   └── sql/init/          # 数据库初始化脚本
│   ├── scripts/
│   │   └── import_all.py      # 向量知识库导入（断点续传）
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # 前端服务
│   ├── app/
│   │   ├── page.tsx           # 首页（法律对话）
│   │   ├── court/page.tsx     # 模拟法庭
│   │   ├── documents/page.tsx # 合同审查
│   │   ├── login/page.tsx     # 登录
│   │   └── lib/api.ts         # API 客户端 + SSE 流
│   ├── components/
│   │   ├── ChatInterface.tsx  # 对话界面
│   │   ├── Sidebar.tsx        # 侧边栏导航
│   │   ├── RightPanel.tsx     # 右侧面板（法条/证据）
│   │   ├── DocumentUpload.tsx # 合同审查工作台
│   │   └── LoginModal.tsx     # 登录弹窗
│   ├── store/useChatStore.ts  # Zustand 全局状态
│   ├── package.json
│   └── Dockerfile
├── litellm/
│   └── config.yaml            # LiteLLM 模型路由配置
├── data/                       # 数据目录（不入 Git）
│   ├── law/                   # 法律法规 JSON
│   ├── lawyer/                # 律师知识 + CAIL2018
│   └── judge/                 # 裁判文书
├── models/                     # AI 模型文件（不入 Git）
│   └── Qwen/Qwen3-Embedding-0.6B/
├── docker-compose.yml          # 生产部署编排
├── deploy/docker-compose.yml   # 简化部署版
└── .env.example                # 环境变量模板
```

## 快速开始

### 环境要求

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.10+ | 后端运行时 |
| Node.js | 18+ | 前端运行时 |
| Redis | 7+ | 缓存 + 会话 |
| PostgreSQL | 16+ | 含 pgvector 扩展 |
| CUDA | 11.8+ | GPU 推理（可选，CPU 也可运行） |
| Git LFS | - | 如需存储模型文件 |

### 1. 克隆项目

```bash
git clone https://github.com/<your-username>/LegalMind-AI.git
cd LegalMind-AI
```

### 2. 环境变量配置

```bash
cp .env.example .env
# 编辑 .env 填入真实密钥
```

`.env` 必填项：

```env
JWT_SECRET_KEY=your-secret-key-at-least-32-characters
DEEPSEEK_API_KEY=your-deepseek-api-key        # DeepSeek API（如使用云端模型）
LITELLM_MASTER_KEY=your-litellm-master-key     # LiteLLM 代理密钥
LITELLM_VIRTUAL_KEY=your-litellm-virtual-key   # LiteLLM 虚拟密钥
```

### 3. 启动基础设施

```bash
# 启动 Redis + PostgreSQL + Qdrant + LiteLLM
docker compose up -d redis postgres qdrant litellm-db litellm
```

等待所有服务健康：
```bash
docker compose ps  # 确认所有服务 healthy
```

### 4. 后端启动

```bash
cd backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动后端
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

后端启动后会自动：
- 连接 Redis / PostgreSQL / Qdrant（带重试降级）
- 加载 Embedding 模型（`models/Qwen/Qwen3-Embedding-0.6B`）
- 启动内存监控后台任务
- 创建默认管理员账号（admin/admin）

### 5. 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问 http://localhost:3000 即可使用。

### 6. 导入法律知识库（首次运行）

```bash
cd backend
source venv/bin/activate

# 全量导入（需要 data/ 目录下有对应数据文件）
python scripts/import_all.py --resume

# 仅验证已有数据
python scripts/import_all.py --verify-only

# 跳过某些数据源
python scripts/import_all.py --resume --skip-lawyer
```

导入脚本支持：
- **断点续传**：`--resume` 参数，中断后可继续
- **分批嵌入**：自动分片 + GPU 加速
- **进度追踪**：`.import_progress/` 目录记录进度

## Docker Compose 一键部署

```bash
# 构建并启动所有服务
docker compose up -d --build

# 查看日志
docker compose logs -f fastapi

# 停止
docker compose down
```

## 核心功能说明

### 模拟法庭辩论

1. 输入案件描述
2. LangGraph 工作流自动编排多轮辩论：
   - **原告代理** → 提出主张与证据
   - **被告代理** → 辩驳与反证
   - **法官** → 归纳争议焦点、引导辩论
   - **调解员** → 提出调解方案
3. SSE 实时流式输出各角色发言
4. 辩论结束后生成汇总报告

### 合同智能审查

1. 上传 PDF / Word / TXT 合同文件
2. 后端自动提取文本（PyMuPDF / python-docx）
3. LangGraph 工作流执行：
   - **条款提取与分类** → 识别合同条款结构
   - **风险扫描** → P0-P4 五级风险评估
   - **漏洞检测** → 缺失条款 / 不公平条款
   - **报告生成** → 结构化 JSON 审查报告
4. 前端展示：合同原文 + 审查结果双标签页

### 法律知识检索

- **Dense 检索**：Qwen3-Embedding-0.6B 向量检索
- **Sparse 检索**：BM25 关键词检索
- **Rerank**：BGE-Reranker 精排
- **知识库规模**：97,000+ 法律法规 + 50,000+ 裁判文书

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/token` | POST | 登录获取 JWT |
| `/api/chat/stream` | GET (SSE) | 法律对话流 |
| `/api/debate/stream` | GET (SSE) | 模拟法庭辩论流 |
| `/api/contract-review/stream` | GET (SSE) | 合同审查流 |
| `/api/documents/upload` | POST | 上传合同文件 |
| `/api/documents/{id}/content` | GET | 获取文档文本内容 |
| `/api/knowledge/search` | POST | 法律知识检索 |
| `/health` | GET | 健康检查 |
| `/metrics` | GET | Prometheus 指标 |

## 配置项

所有配置通过环境变量管理（`backend/app/core/config.py`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接地址 |
| `PG_JUDGE_URL` | - | 裁判文书库 PostgreSQL URL |
| `PG_LAWYER_URL` | - | 律师知识库 PostgreSQL URL |
| `PG_LAW_URL` | - | 法律法规库 PostgreSQL URL |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant 地址 |
| `QDRANT_PATH` | `data/qdrant_data` | Qdrant 本地路径 |
| `EMBEDDING_MODEL` | `models/Qwen/Qwen3-Embedding-0.6B` | 嵌入模型路径 |
| `EMBEDDING_DEVICE` | `cuda` | 嵌入设备 (cuda/cpu) |
| `JWT_SECRET_KEY` | - | JWT 签名密钥 |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | LiteLLM 代理地址 |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | 前端 API 地址 |

## WSL2 内存优化

项目内置内存监控机制，建议在 WSL2 环境下配置 `.wslconfig`：

```ini
# C:\Users\<YourName>\.wslconfig
[wsl2]
memory=19GB    # 24GB 的 80%
swap=4GB
```

修改后需 `wsl --shutdown` 重启生效。

后端自动监控：
- **80% 内存占用** → 告警日志
- **90% 内存占用** → 强制 GC + GPU 缓存释放

## 安全注意事项

- **绝不提交 `.env` 文件** — 已在 `.gitignore` 中排除
- **JWT 密钥** — 生产环境务必更换为强随机字符串
- **默认管理员** — 首次启动创建 admin/admin，请立即修改密码
- **模型文件** — `models/` 目录已排除，需单独下载
- **用户上传** — `backend/uploads/` 已排除，含隐私数据不入 Git

## License

MIT
