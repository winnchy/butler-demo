#!/bin/bash
set -e

# DeepSeek API 配置
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com/v1}"

echo ">>> Starting mock_backend on :8000..."
cd /app/mock_backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

echo ">>> Configuring OpenClaw..."
mkdir -p ~/.openclaw
openclaw config set gateway.mode local 2>/dev/null || true
openclaw config set gateway.auth.token butler-demo-2026 2>/dev/null || true
openclaw config set workspace /app/butler 2>/dev/null || true
# 强制使用 DeepSeek 模型（替代 gpt-5.5）
openclaw config set agents.defaults.model openai/deepseek-chat 2>/dev/null || true
openclaw config set model.default openai/deepseek-chat 2>/dev/null || true

echo ">>> Starting OpenClaw Gateway on :18789..."
openclaw gateway --port 18789 --allow-unconfigured --password butler-demo-2026 &
sleep 5

echo ">>> All services started!"
echo "    mock_backend: http://localhost:8000"
echo "    OpenClaw:     http://localhost:18789"

wait
