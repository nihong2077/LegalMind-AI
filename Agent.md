# Agent.md — 部署与工程约定

本文件记录本项目（LegalMind AI）的部署方式与必须遵守的工程约定，供后续迭代/自动化 Agent 参考。

## 1. 当前部署方式

**单机 Docker Compose**，权威编排为根目录 [docker-compose.yml](docker-compose.yml)。

- 基础设施（拉官方镜像，不本地构建）：`redis`、`postgres`(pgvector/pgvector:pg16)、`qdrant`、`litellm-db`、`litellm`、`jaeger`、`kafka`+`kafka-init`、`prometheus`/`grafana`（`--profile observability` 才启）。
- 应用（本地构建）：`fastapi`（镜像 `legalmind-backend:local`）与 `frontend`（镜像 `legalmind-frontend:local`）；`worker-collab` / `worker-memory` / `worker-doc` 复用 `legalmind-backend:local`，以 `--role` 区分。
- [deploy/docker-compose.yml](deploy/docker-compose.yml) 是精简版（仅 backend/frontend/redis），LLM 须外接 LiteLLM，**完整功能以根 compose 为准**。
- 端口/服务/环境变量细节见 [docs/deployment.md](docs/deployment.md)。

## 2. 一键部署

```bash
cp .env.example .env      # 首次：填入 JWT_SECRET_KEY / DEEPSEEK_API_KEY / LITELLM_MASTER_KEY 等
bash deploy/scripts/docker-deploy.sh
```

脚本 [deploy/scripts/docker-deploy.sh](deploy/scripts/docker-deploy.sh) 依次执行：

1. `docker compose down --remove-orphans`（停旧容器，**保留数据卷**）
2. `docker compose build fastapi frontend`（构建前后端镜像，复用层缓存）
3. `docker image prune -f`（清理构建后残留的旧/无用镜像）
4. `docker compose up -d --remove-orphans`（启动默认服务集）

可选开关：`SKIP_PRUNE=1` 跳过清理、`NO_DOWN=1` 不先停旧容器。

## 3. 镜像命名约定

| 服务 | 镜像 tag | 说明 |
|---|---|---|
| 后端（fastapi + 3 worker） | `legalmind-backend:local` | 多阶段构建，torch 走 `.wheelcache` 离线安装 |
| 前端（frontend） | `legalmind-frontend:local` | 多阶段 + Next.js `output: 'standalone'` |

- 统一使用 `:local` 后缀，禁止使用 `:latest`。
- 容器名统一 `legalmind-*` 前缀（`-api` 对应后端）。

## 4. 构建时清理旧镜像（约定）

**每次构建应用镜像后，必须清理被取代的旧镜像。**

- 原则：**先 build 再 prune**。同一 tag 重建后，旧镜像变成悬空（dangling）镜像，由 `docker image prune -f` 回收；这样既保住构建层缓存，又能删除「前面没用的镜像」。
- **禁止**把清理动作写进 Dockerfile 或 compose（Docker 无构建期钩子），清理一律放在一键部署脚本中执行。
- **禁止**使用 `docker system prune -a` 或 `docker builder prune`（会误删构建缓存/无用但仍在用的基础镜像）；只允许 `docker image prune -f`（仅删悬空镜像）。
- 禁止 `docker compose down -v`（会连同 PG/Redis/Qdrant 数据一起删除）。

### 前端构建要点（易错）

- `NEXT_PUBLIC_*` 变量在 **next build 时被内联**进产物，运行期注入无效 → 必须在 compose 的 `build.args` 中传入 `NEXT_PUBLIC_API_URL`（见根 compose 的 `frontend` 段）。
- 必须保留 [frontend/.dockerignore](frontend/.dockerignore)：排除 `node_modules/`、`.next/`，否则构建上下文会被本地依赖与缓存污染。
- 依赖安装用 `npm ci`（可复现），不用 `npm install`。
