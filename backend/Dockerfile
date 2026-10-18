# syntax=docker/dockerfile:1
# ---- builder：安装全部依赖到独立前缀 ----
FROM python:3.12-slim AS builder

# pip 网络韧性：大 wheel 在慢网下默认 15s 容易读超时
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 可选镜像加速（国内构建）：
#   docker build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ ...
ARG PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /build
COPY requirements.txt .

# torch 主包 554MB + 整棵 CUDA 依赖闭包约 2.2GB，代理链路偶发截断；
# 宿主机预下载 + sha256 校验后随构建上下文进入，容器内完全离线安装。
# 预下载脚本：scripts/predownload_torch_wheels.py（.wheelcache 不入 git）
COPY .wheelcache /wheels
RUN if ls /wheels/torch-*.whl >/dev/null 2>&1; then \
      pip install --no-cache-dir --prefix=/install --no-index --find-links=/wheels /wheels/torch-*.whl; \
    else \
      pip install --no-cache-dir --prefix=/install "torch>=2.0.0"; \
    fi
# 让 pip 看到 Step7 已装入 /install 的 torch 闭包（--prefix 不在默认 sys.path 上），
# 从而将其判定为"已满足"直接跳过；其余依赖走索引在线安装
ENV PYTHONPATH=/install/lib/python3.12/site-packages
RUN pip install --no-cache-dir --prefix=/install --find-links=/wheels -r requirements.txt

# ---- runtime：只继承 site-packages 与应用代码（不含 2.2GB wheel 缓存/开发数据）----
FROM python:3.12-slim

# compose 健康检查使用 curl；libgomp1 为 torch/onnx 数值库运行所需
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
# 仅拷贝运行时代码；data/uploads 建为空目录（本地 Qdrant 与合同上传写入用）
COPY app ./app
RUN mkdir -p data/qdrant_data uploads

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
