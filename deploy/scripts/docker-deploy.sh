#!/usr/bin/env bash
# LegalMind AI 一键部署：构建前后端镜像 → 清理旧/无用镜像 → 启动默认服务集
#
# 用法：
#   bash deploy/scripts/docker-deploy.sh            # 完整一键部署
#   SKIP_PRUNE=1 bash deploy/scripts/docker-deploy.sh   # 跳过镜像清理
#   NO_DOWN=1   bash deploy/scripts/docker-deploy.sh    # 不先停旧容器（保留现场）
#
# 约定：不改宿主 docker 配置，不动数据卷（down 不带 -v）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[deploy]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker ≥ 24"
docker compose version >/dev/null 2>&1 || die "需要 Docker Compose v2（docker compose 子命令）"

[[ -f .env ]] || die "缺少 .env（可 cp .env.example .env 后填入 JWT_SECRET_KEY / DEEPSEEK_API_KEY / LITELLM_MASTER_KEY 等）"

# 1) 停旧容器（保留数据卷），释放被运行容器占用的旧镜像引用
if [[ "${NO_DOWN:-0}" != "1" ]]; then
  log "停止旧容器（保留数据卷）"
  docker compose down --remove-orphans
fi

# 2) 构建前后端镜像（复用层缓存；同一 tag 重建后旧镜像会变悬空，交由第 3 步回收）
log "构建后端镜像 legalmind-backend:local 与前端镜像 legalmind-frontend:local"
docker compose build fastapi frontend

# 3) 构建期清理：删除被新镜像取代的旧镜像（悬空 tag）与无引用层
if [[ "${SKIP_PRUNE:-0}" != "1" ]]; then
  log "清理构建后残留的无用镜像（dangling）"
  docker image prune -f
fi

# 4) 启动默认服务集
log "启动默认服务集"
docker compose up -d --remove-orphans

log "完成。前端 http://localhost:3000 ｜ 后端 http://localhost:8000/docs"
docker compose ps
