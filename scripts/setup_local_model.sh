#!/usr/bin/env bash
# ============================================================
# LegalMind AI - 本地微调模型部署脚本
# 将 GGUF 量化模型注册到 Ollama，提供 OpenAI 兼容推理接口
# ============================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="${PROJECT_ROOT}/models/a-----------lora/LegalMind AI"
MODELFILE="${MODEL_DIR}/Modelfile"
GGUF_FILE="legalmind-ai-q4_k_m.gguf"
OLLAMA_MODEL_NAME="legalmind-ai"
OLLAMA_API_BASE="http://localhost:11434"

echo "============================================"
echo "  LegalMind AI 本地微调模型部署"
echo "============================================"
echo "模型目录: ${MODEL_DIR}"
echo "Ollama 模型名: ${OLLAMA_MODEL_NAME}"
echo ""

# 1. 检查 Ollama 是否安装
if ! command -v ollama >/dev/null 2>&1; then
  echo "❌ 未检测到 ollama，正在安装..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
echo "✅ ollama 版本: $(ollama --version)"

# 2. 启动 Ollama 服务（守护进程模式）
if ! curl -sf "${OLLAMA_API_BASE}/api/tags" >/dev/null 2>&1; then
  echo "启动 ollama serve..."
  nohup ollama serve > /tmp/ollama.log 2>&1 &
  sleep 3
  if ! curl -sf "${OLLAMA_API_BASE}/api/tags" >/dev/null 2>&1; then
    echo "❌ ollama serve 启动失败，请查看 /tmp/ollama.log"
    exit 1
  fi
fi
echo "✅ ollama 服务已运行"

# 3. 校验 GGUF 模型文件存在
if [ ! -f "${MODEL_DIR}/${GGUF_FILE}" ]; then
  echo "❌ 找不到模型文件: ${MODEL_DIR}/${GGUF_FILE}"
  exit 1
fi
echo "✅ GGUF 模型文件存在"

# 4. 校验 Modelfile
if [ ! -f "${MODELFILE}" ]; then
  echo "❌ 找不到 Modelfile: ${MODELFILE}"
  exit 1
fi
echo "✅ Modelfile 存在"

# 5. 注册模型到 Ollama
echo ""
echo "正在注册模型到 Ollama（首次会加载权重，请耐心等待）..."
cd "${MODEL_DIR}"
ollama create "${OLLAMA_MODEL_NAME}" -f Modelfile

# 6. 验证模型可用
echo ""
echo "验证模型可用性..."
if ollama list | grep -q "${OLLAMA_MODEL_NAME}"; then
  echo "✅ 模型已注册成功"
else
  echo "❌ 模型注册失败"
  exit 1
fi

# 7. 快速冒烟测试
echo ""
echo "进行冒烟测试..."
RESPONSE=$(ollama run "${OLLAMA_MODEL_NAME}" "你好，请用一句话介绍自己" 2>&1 | head -5)
echo "模型响应: ${RESPONSE}"

echo ""
echo "============================================"
echo "✅ 部署完成！"
echo "============================================"
echo "OpenAI 兼容接口: ${OLLAMA_API_BASE}/v1"
echo "模型名: ${OLLAMA_MODEL_NAME}"
echo ""
echo "在 LegalMind AI 前端切换到「法律领域微调模型」即可使用"
