# syntax=docker/dockerfile:1
# ---- builder：装全量依赖并执行 next build ----
FROM node:20-slim AS builder

WORKDIR /app

# 先装依赖再拷源码，最大化利用层缓存
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# NEXT_PUBLIC_* 在构建期被内联进产物，运行期再注入无效，必须在 build 前传入
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# public/ 可能为空目录，先兜底创建以满足下方 COPY
RUN mkdir -p public && npm run build

# ---- runner：仅保留 standalone 产物（含最小 node_modules），不含源码/devDeps ----
FROM node:20-slim AS runner

WORKDIR /app
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
